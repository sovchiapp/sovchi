import base64
import hashlib
import logging
import time
import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.core import core
from .models import SubscriptionPlan, UserSubscription, Payment, DailyService, UserDailyService
from .serializers import (
    SubscriptionPlanSerializer,
    DailyServiceSerializer,
    UserSubscriptionSerializer,
    PaymentSerializer,
    CreatePaymentSerializer,
    CreateServicePaymentSerializer,
    get_debug_price,
)

logger = logging.getLogger(__name__)


class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class PlansListView(ListAPIView):
    queryset = SubscriptionPlan.objects.filter(is_active=True)
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ServicesListView(ListAPIView):
    queryset = DailyService.objects.filter(is_active=True)
    serializer_class = DailyServiceSerializer
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class MySubscriptionView(RetrieveAPIView):
    serializer_class = UserSubscriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        subscription, _ = UserSubscription.objects.get_or_create(
            user=self.request.user,
            defaults={'plan': SubscriptionPlan.get_free_plan()}
        )
        return subscription

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class CreatePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if not user.is_verified:
            return Response(
                {"error": "user_not_verified"},
                status=status.HTTP_403_FORBIDDEN
            )

        if hasattr(user,
                   'subscription') and user.subscription.plan.plan_type == 'premium' and user.subscription.is_active:
            return Response(
                {"error": "subscription_still_active"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = CreatePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        plan = SubscriptionPlan.objects.get(id=serializer.validated_data['plan_id'])
        provider = serializer.validated_data['provider']
        platform = serializer.validated_data['platform']
        transaction_id = f"TXN-{uuid.uuid4().hex[:12].upper()}"

        amount = get_debug_price(plan.price, 'premium')

        payment = Payment.objects.create(
            user=request.user,
            plan=plan,
            provider=provider,
            platform=platform,
            amount=amount,
            transaction_id=transaction_id,
        )

        logger.info(f"Payment created (subscription): payment={payment.id} user={user.id} provider={provider} amount={amount} plan={plan.plan_type}")

        if provider == 'click':
            payment_url = generate_click_url(payment)
        elif provider == 'payme':
            payment_url = generate_payme_url(payment)
        else:
            payment_url = None

        return Response({
            'transaction_id': payment.transaction_id,
            'payment_url': payment_url,
            'amount': payment.amount,
        }, status=status.HTTP_201_CREATED)


class CreateServicePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if not user.is_verified:
            return Response(
                {"error": "user_not_verified"},
                status=status.HTTP_403_FORBIDDEN
            )

        if hasattr(user,
                   'subscription') and user.subscription.plan.plan_type == 'premium' and user.subscription.is_active:
            return Response(
                {"error": "premium_user_cannot_buy_service"},
                status=status.HTTP_403_FORBIDDEN
            )

        active_boost = UserDailyService.objects.filter(
            user=user,
            boost_expires_at__gt=timezone.now()
        ).exists()

        if active_boost:
            return Response(
                {"error": "boost_still_active"},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = CreateServicePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = DailyService.get_default()
        provider = serializer.validated_data['provider']
        platform = serializer.validated_data['platform']
        transaction_id = f"TXN-{uuid.uuid4().hex[:12].upper()}"

        amount = get_debug_price(service.price, 'daily_service')

        payment = Payment.objects.create(
            user=request.user,
            payment_type='service',
            service=service,
            provider=provider,
            platform=platform,
            amount=amount,
            transaction_id=transaction_id,
        )

        logger.info(f"Payment created (service): payment={payment.id} user={user.id} provider={provider} amount={amount}")

        if provider == 'click':
            payment_url = generate_click_url(payment)
        elif provider == 'payme':
            payment_url = generate_payme_url(payment)
        else:
            payment_url = None

        return Response({
            'transaction_id': payment.transaction_id,
            'payment_url': payment_url,
            'amount': payment.amount,
        }, status=status.HTTP_201_CREATED)


class PaymentStatusView(RetrieveAPIView):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'transaction_id'

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user)

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class PaymentHistoryView(ListAPIView):
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        return Payment.objects.filter(user=self.request.user)

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


def get_return_url(payment):
    base_url = core.PAYMENT_RETURN_URL_MOBILE if payment.platform == 'mobile' else core.PAYMENT_RETURN_URL_TG_APP
    return f"{base_url}?txn={payment.transaction_id}"


def generate_click_url(payment):
    return_url = get_return_url(payment)
    return (
        f"https://my.click.uz/services/pay"
        f"?service_id={core.CLICK_SERVICE_ID}"
        f"&merchant_id={core.CLICK_MERCHANT_ID}"
        f"&amount={payment.amount}"
        f"&transaction_param={payment.id}"
        f"&return_url={return_url}"
    )


def generate_payme_url(payment):
    merchant_id = core.PAYME_MERCHANT_ID
    amount = payment.amount * 100
    account_field = core.PAYME_ACCOUNT_FIELD
    account_value = payment.id
    return_url = get_return_url(payment)
    params = f"m={merchant_id};ac.{account_field}={account_value};a={amount};c={return_url}"
    encoded = base64.b64encode(params.encode()).decode()
    return f"https://checkout.paycom.uz/{encoded}"


def make_click_prepare_sign(click_trans_id, service_id, secret_key, merchant_trans_id, amount, action, sign_time):
    raw = f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}{amount}{action}{sign_time}"
    return hashlib.md5(raw.encode()).hexdigest()


def make_click_complete_sign(click_trans_id, service_id, secret_key, merchant_trans_id, merchant_prepare_id, amount,
                             action, sign_time):
    raw = f"{click_trans_id}{service_id}{secret_key}{merchant_trans_id}{merchant_prepare_id}{amount}{action}{sign_time}"
    return hashlib.md5(raw.encode()).hexdigest()


def check_click_amount(click_amount, payment_amount):
    try:
        return abs(float(click_amount) - float(payment_amount)) < 0.01
    except (ValueError, TypeError):
        return False


class ClickPrepareView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        data = request.data
        click_trans_id = data.get('click_trans_id')
        service_id = data.get('service_id')
        merchant_trans_id = data.get('merchant_trans_id')
        amount = data.get('amount')
        action = data.get('action')
        sign_time = data.get('sign_time')
        sign_string = data.get('sign_string')

        if str(service_id) != str(core.CLICK_SERVICE_ID):
            return Response({
                'error': -8,
                'error_note': 'Error in request from click'
            }, status=status.HTTP_200_OK)

        my_sign = make_click_prepare_sign(
            click_trans_id, service_id, core.CLICK_SECRET_KEY,
            merchant_trans_id, amount, action, sign_time
        )

        if my_sign != sign_string:
            logger.warning(f"Click prepare sign check failed: merchant_trans_id={merchant_trans_id} click_trans_id={click_trans_id}")
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'error': -1,
                'error_note': 'SIGN CHECK FAILED!'
            }, status=status.HTTP_200_OK)

        try:
            payment = Payment.objects.get(id=merchant_trans_id)
        except (Payment.DoesNotExist, ValueError):
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'error': -5,
                'error_note': 'User does not exist'
            }, status=status.HTTP_200_OK)

        if payment.status == 'cancelled':
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'error': -9,
                'error_note': 'Transaction cancelled'
            }, status=status.HTTP_200_OK)

        if payment.status == 'completed':
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'error': -4,
                'error_note': 'Already paid'
            }, status=status.HTTP_200_OK)

        if not check_click_amount(amount, payment.amount):
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'error': -2,
                'error_note': 'Incorrect parameter amount'
            }, status=status.HTTP_200_OK)

        return Response({
            'click_trans_id': int(click_trans_id),
            'merchant_trans_id': str(merchant_trans_id),
            'merchant_prepare_id': payment.id,
            'error': 0,
            'error_note': 'Success'
        }, status=status.HTTP_200_OK)


class ClickCompleteView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        data = request.data
        click_trans_id = data.get('click_trans_id')
        service_id = data.get('service_id')
        merchant_trans_id = data.get('merchant_trans_id')
        merchant_prepare_id = data.get('merchant_prepare_id')
        amount = data.get('amount')
        action = data.get('action')
        sign_time = data.get('sign_time')
        sign_string = data.get('sign_string')
        error = int(data.get('error', 0))

        if str(service_id) != str(core.CLICK_SERVICE_ID):
            return Response({
                'error': -8,
                'error_note': 'Error in request from click'
            }, status=status.HTTP_200_OK)

        my_sign = make_click_complete_sign(
            click_trans_id, service_id, core.CLICK_SECRET_KEY,
            merchant_trans_id, merchant_prepare_id, amount, action, sign_time
        )

        if my_sign != sign_string:
            logger.warning(f"Click complete sign check failed: merchant_trans_id={merchant_trans_id} click_trans_id={click_trans_id}")
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'error': -1,
                'error_note': 'SIGN CHECK FAILED!'
            }, status=status.HTTP_200_OK)

        try:
            payment = Payment.objects.get(id=merchant_trans_id)
        except (Payment.DoesNotExist, ValueError):
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'error': -5,
                'error_note': 'User does not exist'
            }, status=status.HTTP_200_OK)

        if str(merchant_prepare_id) != str(payment.id):
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'error': -6,
                'error_note': 'Transaction does not exist'
            }, status=status.HTTP_200_OK)

        if payment.status == 'cancelled':
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'merchant_confirm_id': payment.id,
                'error': -9,
                'error_note': 'Transaction cancelled'
            }, status=status.HTTP_200_OK)

        if payment.status == 'completed':
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'merchant_confirm_id': payment.id,
                'error': -4,
                'error_note': 'Already paid'
            }, status=status.HTTP_200_OK)

        if error < 0:
            payment.cancel()
            logger.info(f"Payment cancelled (Click): payment={payment.id} user={payment.user_id} amount={payment.amount} error={error}")
            return Response({
                'click_trans_id': click_trans_id,
                'merchant_trans_id': merchant_trans_id,
                'merchant_confirm_id': payment.id,
                'error': -9,
                'error_note': 'Transaction cancelled'
            }, status=status.HTTP_200_OK)

        payment.external_id = str(click_trans_id)
        payment.complete()

        logger.info(f"Payment completed (Click): payment={payment.id} user={payment.user_id} amount={payment.amount} click_trans_id={click_trans_id}")

        return Response({
            'click_trans_id': int(click_trans_id),
            'merchant_trans_id': str(merchant_trans_id),
            'merchant_confirm_id': payment.id,
            'error': 0,
            'error_note': 'Success'
        }, status=status.HTTP_200_OK)


PAYME_ERROR_INVALID_AMOUNT = -31001
PAYME_ERROR_ORDER_NOT_FOUND = -31050
PAYME_ERROR_CANT_PERFORM = -31008
PAYME_ERROR_ALREADY_PAID = -31060
PAYME_ERROR_TRANSACTION_NOT_FOUND = -31003
PAYME_ERROR_INVALID_ACCOUNT = -31050
PAYME_ERROR_ORDER_OCCUPIED = -31051
PAYME_ERROR_METHOD_NOT_FOUND = -32601
PAYME_ERROR_INVALID_JSON = -32700
PAYME_ERROR_UNAUTHORIZED = -32504


def payme_error_response(rpc_id, code, message, data=None):
    response = {
        'jsonrpc': '2.0',
        'id': rpc_id,
        'error': {
            'code': code,
            'message': message,
        }
    }
    if data:
        response['error']['data'] = data
    return response


def payme_success_response(rpc_id, result):
    return {
        'jsonrpc': '2.0',
        'id': rpc_id,
        'result': result
    }


def get_current_timestamp():
    return int(time.time() * 1000)


class PaymeWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        auth_header = request.headers.get('Authorization', '')
        if not self._check_auth(auth_header):
            logger.warning("Payme webhook unauthorized: auth check failed")
            return Response(
                payme_error_response(None, PAYME_ERROR_UNAUTHORIZED, "Unauthorized"),
                status=status.HTTP_200_OK
            )

        try:
            rpc_id = request.data.get('id')
            method = request.data.get('method')
            params = request.data.get('params', {})
        except Exception:
            return Response(
                payme_error_response(None, PAYME_ERROR_INVALID_JSON, "Parse error"),
                status=status.HTTP_200_OK
            )

        method_handlers = {
            'CheckPerformTransaction': self._check_perform_transaction,
            'CreateTransaction': self._create_transaction,
            'PerformTransaction': self._perform_transaction,
            'CancelTransaction': self._cancel_transaction,
            'CheckTransaction': self._check_transaction,
            'GetStatement': self._get_statement,
        }

        handler = method_handlers.get(method)
        if not handler:
            return Response(
                payme_error_response(rpc_id, PAYME_ERROR_METHOD_NOT_FOUND, f"Method not found: {method}"),
                status=status.HTTP_200_OK
            )

        result = handler(rpc_id, params)
        return Response(result, status=status.HTTP_200_OK)

    def _check_auth(self, auth_header):
        if not auth_header.startswith('Basic '):
            return False
        try:
            encoded = auth_header.split(' ')[1]
            decoded = base64.b64decode(encoded).decode('utf-8')
            username, password = decoded.split(':')
            return password == core.PAYME_SECRET_KEY
        except Exception:
            return False

    def _check_perform_transaction(self, rpc_id, params):
        account = params.get('account', {})
        amount = params.get('amount')

        payment_id = account.get(core.PAYME_ACCOUNT_FIELD)
        if not payment_id:
            return payme_error_response(rpc_id, PAYME_ERROR_INVALID_ACCOUNT, "Account field not found")

        try:
            payment = Payment.objects.get(id=payment_id)
        except (Payment.DoesNotExist, ValueError):
            return payme_error_response(rpc_id, PAYME_ERROR_ORDER_NOT_FOUND, "Order not found")

        expected_amount = payment.amount * 100
        if amount != expected_amount:
            return payme_error_response(rpc_id, PAYME_ERROR_INVALID_AMOUNT, "Invalid amount")

        if payment.status == 'completed':
            return payme_error_response(rpc_id, PAYME_ERROR_ALREADY_PAID, "Already paid")

        if payment.status == 'cancelled':
            return payme_error_response(rpc_id, PAYME_ERROR_CANT_PERFORM, "Order cancelled")

        return payme_success_response(rpc_id, {
            'allow': True,
            'detail': {
                'receipt_type': 0,
                'items': [{
                    'title': f"{payment.id}",
                    'price': amount,
                    'count': 1,
                    'code': '10899001001000000',
                    'package_code': '1209779',
                    'vat_percent': 0,
                }]
            }
        })

    def _create_transaction(self, rpc_id, params):
        payme_id = params.get('id')
        account = params.get('account', {})
        amount = params.get('amount')
        time_param = params.get('time')

        payment_id = account.get(core.PAYME_ACCOUNT_FIELD)

        try:
            payment = Payment.objects.get(id=payment_id)
        except (Payment.DoesNotExist, ValueError):
            return payme_error_response(rpc_id, PAYME_ERROR_ORDER_NOT_FOUND, "Order not found")

        expected_amount = payment.amount * 100
        if amount != expected_amount:
            return payme_error_response(rpc_id, PAYME_ERROR_INVALID_AMOUNT, "Invalid amount")

        if payment.external_id and payment.external_id != payme_id:
            return payme_error_response(rpc_id, PAYME_ERROR_ORDER_OCCUPIED, "Another transaction exists")

        if payment.status == 'completed':
            return payme_error_response(rpc_id, PAYME_ERROR_ALREADY_PAID, "Already paid")

        if payment.status == 'cancelled':
            return payme_error_response(rpc_id, PAYME_ERROR_CANT_PERFORM, "Order cancelled")

        if not payment.external_id:
            payment.external_id = payme_id
            payment.payme_create_time = time_param
            payment.save()
            logger.info(f"Payme transaction created: payment={payment.id} user={payment.user_id} amount={payment.amount}")

        return payme_success_response(rpc_id, {
            'create_time': payment.payme_create_time,
            'transaction': str(payment.id),
            'state': 1,
        })

    def _perform_transaction(self, rpc_id, params):
        payme_id = params.get('id')

        try:
            payment = Payment.objects.get(external_id=payme_id)
        except Payment.DoesNotExist:
            return payme_error_response(rpc_id, PAYME_ERROR_TRANSACTION_NOT_FOUND, "Transaction not found")

        if payment.status == 'completed':
            return payme_success_response(rpc_id, {
                'transaction': str(payment.id),
                'perform_time': int(
                    payment.completed_at.timestamp() * 1000) if payment.completed_at else get_current_timestamp(),
                'state': 2,
            })

        if payment.status == 'cancelled':
            return payme_error_response(rpc_id, PAYME_ERROR_CANT_PERFORM, "Transaction cancelled")

        payment.complete()

        logger.info(f"Payment completed (Payme): payment={payment.id} user={payment.user_id} amount={payment.amount}")

        return payme_success_response(rpc_id, {
            'transaction': str(payment.id),
            'perform_time': int(payment.completed_at.timestamp() * 1000),
            'state': 2,
        })

    def _cancel_transaction(self, rpc_id, params):
        payme_id = params.get('id')
        reason = params.get('reason')

        try:
            payment = Payment.objects.get(external_id=payme_id)
        except Payment.DoesNotExist:
            return payme_error_response(rpc_id, PAYME_ERROR_TRANSACTION_NOT_FOUND, "Transaction not found")

        if payment.status == 'cancelled':
            return payme_success_response(rpc_id, {
                'transaction': str(payment.id),
                'cancel_time': payment.payme_cancel_time,
                'state': payment.payme_state,
            })

        state = -2 if payment.status == 'completed' else -1
        cancel_time = get_current_timestamp()

        payment.payme_cancel_time = cancel_time
        payment.payme_state = state
        payment.payme_cancel_reason = reason
        payment.cancel()

        logger.info(f"Payment cancelled (Payme): payment={payment.id} user={payment.user_id} amount={payment.amount} reason={reason} state={state}")

        return payme_success_response(rpc_id, {
            'transaction': str(payment.id),
            'cancel_time': cancel_time,
            'state': state,
        })

    def _check_transaction(self, rpc_id, params):
        payme_id = params.get('id')

        try:
            payment = Payment.objects.get(external_id=payme_id)
        except Payment.DoesNotExist:
            return payme_error_response(rpc_id, PAYME_ERROR_TRANSACTION_NOT_FOUND, "Transaction not found")

        if payment.status == 'completed':
            state = 2
        elif payment.status == 'cancelled':
            state = payment.payme_state or -1
        else:
            state = 1

        return payme_success_response(rpc_id, {
            'create_time': payment.payme_create_time or int(payment.created_at.timestamp() * 1000),
            'perform_time': int(payment.completed_at.timestamp() * 1000) if payment.completed_at else 0,
            'cancel_time': payment.payme_cancel_time or 0,
            'transaction': str(payment.id),
            'state': state,
            'reason': payment.payme_cancel_reason,
        })

    def _get_statement(self, rpc_id, params):
        from_time = params.get('from')
        to_time = params.get('to')

        payments = Payment.objects.filter(
            provider='payme',
            external_id__isnull=False,
            payme_create_time__gte=from_time,
            payme_create_time__lte=to_time
        ).order_by('payme_create_time')

        transactions = []
        for payment in payments:

            if payment.status == 'completed':
                state = 2
            elif payment.status == 'cancelled':
                state = payment.payme_state or -1
            else:
                state = 1

            transactions.append({
                'id': payment.external_id,
                'time': payment.payme_create_time or int(payment.created_at.timestamp() * 1000),
                'amount': payment.amount * 100,
                'account': {
                    core.PAYME_ACCOUNT_FIELD: payment.id
                },
                'create_time': payment.payme_create_time or int(payment.created_at.timestamp() * 1000),
                'perform_time': int(payment.completed_at.timestamp() * 1000) if payment.completed_at else 0,
                'cancel_time': payment.payme_cancel_time or 0,
                'transaction': str(payment.id),
                'state': state,
                'reason': payment.payme_cancel_reason,
            })

        return payme_success_response(rpc_id, {
            'transactions': transactions
        })

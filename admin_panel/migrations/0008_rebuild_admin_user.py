from django.db import migrations, models
import django.db.models.deletion


def clear_old_admin_references(apps, schema_editor):
    """Eski admin reference larni tozalash"""
    BroadcastMessage = apps.get_model('admin_panel', 'BroadcastMessage')
    AdminSupportChat = apps.get_model('admin_panel', 'AdminSupportChat')
    AdminSupportMessage = apps.get_model('admin_panel', 'AdminSupportMessage')

    BroadcastMessage.objects.all().update(admin=None)
    AdminSupportChat.objects.all().update(admin_user=None)
    AdminSupportMessage.objects.filter(sender_type='admin').update(admin_sender=None)


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0007_add_broadcast_filters'),
    ]

    operations = [
        # 0. Eski reference larni tozalash
        migrations.RunPython(clear_old_admin_references, migrations.RunPython.noop),

        # 1. Eski jadvallarni o'chirish
        migrations.DeleteModel(
            name='AdminActivityLog',
        ),
        migrations.DeleteModel(
            name='AdminUser',
        ),

        # 2. Yangi AdminUser yaratish
        migrations.CreateModel(
            name='AdminUser',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('password', models.CharField(max_length=128)),
                ('full_name', models.CharField(max_length=150)),
                ('phone', models.CharField(blank=True, max_length=20, null=True)),
                ('telegram_id', models.IntegerField(blank=True, help_text='For notifications', null=True)),
                ('role', models.CharField(choices=[
                    ('founder', 'Founder'),
                    ('cpo', 'Chief Product Owner'),
                    ('marketing_advisor', 'Marketing Advisor'),
                    ('dev_tech_ops', 'Dev/Tech/Verification Ops'),
                ], max_length=20)),
                ('is_active', models.BooleanField(default=True)),
                ('offboarded_at', models.DateTimeField(blank=True, null=True)),
                ('last_login', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Admin User',
                'verbose_name_plural': 'Admin Users',
                'db_table': 'admin_users',
            },
        ),
        migrations.AddIndex(
            model_name='adminuser',
            index=models.Index(fields=['email'], name='admin_users_email_b7e5f0_idx'),
        ),
        migrations.AddIndex(
            model_name='adminuser',
            index=models.Index(fields=['role', 'is_active'], name='admin_users_role_e8c2a1_idx'),
        ),

        # 3. PermissionGrant yaratish
        migrations.CreateModel(
            name='PermissionGrant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('permission_area', models.CharField(max_length=30)),
                ('permission_level', models.CharField(max_length=10)),
                ('is_active', models.BooleanField(default=True)),
                ('granted_at', models.DateTimeField(auto_now_add=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('granted_to', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='received_grants', to='admin_panel.adminuser')),
                ('granted_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='given_grants', to='admin_panel.adminuser')),
                ('revoked_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='revoked_grants', to='admin_panel.adminuser')),
            ],
            options={
                'db_table': 'admin_permission_grants',
            },
        ),
        migrations.AddIndex(
            model_name='permissiongrant',
            index=models.Index(fields=['granted_to', 'is_active'], name='admin_permi_granted_a1b2c3_idx'),
        ),
        migrations.AddIndex(
            model_name='permissiongrant',
            index=models.Index(fields=['permission_area', 'is_active'], name='admin_permi_permiss_d4e5f6_idx'),
        ),

        # 4. PermissionRequest yaratish
        migrations.CreateModel(
            name='PermissionRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('permission_area', models.CharField(max_length=30)),
                ('requested_level', models.CharField(max_length=10)),
                ('reason', models.TextField()),
                ('status', models.CharField(choices=[
                    ('pending', 'Pending'),
                    ('approved', 'Approved'),
                    ('rejected', 'Rejected'),
                ], default='pending', max_length=10)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('rejection_reason', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('requester', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='permission_requests', to='admin_panel.adminuser')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_requests', to='admin_panel.adminuser')),
            ],
            options={
                'ordering': ['-created_at'],
                'db_table': 'admin_permission_requests',
            },
        ),
        migrations.AddIndex(
            model_name='permissionrequest',
            index=models.Index(fields=['status', '-created_at'], name='admin_permi_status_g7h8i9_idx'),
        ),
        migrations.AddIndex(
            model_name='permissionrequest',
            index=models.Index(fields=['requester', 'status'], name='admin_permi_request_j0k1l2_idx'),
        ),

        # 5. AdminSupportChat va AdminSupportMessage da admin_user FK ni yangilash
        migrations.AlterField(
            model_name='adminsupportchat',
            name='admin_user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_chats', to='admin_panel.adminuser'),
        ),
        migrations.AlterField(
            model_name='adminsupportmessage',
            name='admin_sender',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='support_messages_sent', to='admin_panel.adminuser'),
        ),

        # 6. BroadcastMessage da admin FK ni yangilash
        migrations.AlterField(
            model_name='broadcastmessage',
            name='admin',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='broadcast_messages', to='admin_panel.adminuser'),
        ),
    ]

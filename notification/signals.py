from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from notification.models import Notification
from notification.services import create_notification as _create


def _post_thumbnail(post):
    image = post.images.first()
    if not image or not image.image:
        return None
    try:
        return image.image.url
    except Exception:
        return None


@receiver(post_save, sender='matching.Like')
def on_like_created(sender, instance, created, **kwargs):
    if not created:
        return
    from matching.utils import can_see_likes
    if not can_see_likes(instance.target):
        return
    _create(instance.target_id, instance.user_id, 'like', target_id=instance.id)


@receiver(post_save, sender='matching.Match')
def on_match_created(sender, instance, created, **kwargs):
    if not created:
        return
    _create(instance.user1_id, instance.user2_id, 'match', target_id=instance.id)
    _create(instance.user2_id, instance.user1_id, 'match', target_id=instance.id)


@receiver(post_save, sender='community.PostLike')
def on_post_like_created(sender, instance, created, **kwargs):
    if not created:
        return
    post = instance.post
    _create(post.author_id, instance.author_id, 'post_like',
            target_id=post.id, image_url=_post_thumbnail(post))


@receiver(post_save, sender='community.Comment')
def on_comment_created(sender, instance, created, **kwargs):
    if not created:
        return
    post = instance.post
    _create(post.author_id, instance.author_id, 'comment',
            target_id=instance.id, preview_text=instance.content[:200],
            image_url=_post_thumbnail(post))


@receiver(post_save, sender='community.CommentLike')
def on_comment_like_created(sender, instance, created, **kwargs):
    if not created:
        return
    comment = instance.comment
    _create(comment.author_id, instance.author_id, 'comment_like',
            target_id=comment.id, preview_text=comment.content[:200],
            image_url=_post_thumbnail(comment.post))


@receiver(post_delete, sender='matching.Like')
def on_like_deleted(sender, instance, **kwargs):
    Notification.objects.filter(type='like', target_id=instance.id).delete()


@receiver(post_delete, sender='matching.Match')
def on_match_deleted(sender, instance, **kwargs):
    Notification.objects.filter(type='match', target_id=instance.id).delete()


@receiver(post_delete, sender='community.PostLike')
def on_post_like_deleted(sender, instance, **kwargs):
    Notification.objects.filter(
        type='post_like', target_id=instance.post_id, actor_id=instance.author_id
    ).delete()


@receiver(post_delete, sender='community.Comment')
def on_comment_deleted(sender, instance, **kwargs):
    Notification.objects.filter(type='comment', target_id=instance.id).delete()


@receiver(post_delete, sender='community.CommentLike')
def on_comment_like_deleted(sender, instance, **kwargs):
    Notification.objects.filter(
        type='comment_like', target_id=instance.comment_id, actor_id=instance.author_id
    ).delete()

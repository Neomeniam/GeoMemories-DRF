from django.contrib.gis.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

class User(AbstractUser):
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

class Post(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    caption = models.TextField()
    image = models.ImageField(upload_to='post_images/', blank=True, null=True)
    location = models.PointField(srid=4326, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Post by {self.author.username} at {self.created_at.strftime("%Y-%m-%d %H:%M")}'

class Comment(models.Model):
    post = models.ForeignKey(Post, related_name='comments', on_delete=models.CASCADE)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Comment by {self.author.username} on {self.post}'

class Like(models.Model):
    post = models.ForeignKey(Post, related_name='likes', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'user')

    def __str__(self):
        return f'{self.user.username} likes {self.post}'

class Friendship(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_ACCEPTED = 'accepted'
    STATUS_DECLINED = 'declined'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_DECLINED, 'Declined'),
    ]

    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='friendship_requests_sent', on_delete=models.CASCADE)
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='friendship_requests_received', on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('from_user', 'to_user')

    def __str__(self):
        return f'Request from {self.from_user.username} to {self.to_user.username} - {self.get_status_display()}'

# --- NEW: Notification Model ---
class Notification(models.Model):
    TYPE_LIKE = 'like'
    TYPE_COMMENT = 'comment'
    TYPE_FRIEND_REQUEST = 'friend_request'

    TYPE_CHOICES = [
        (TYPE_LIKE, 'Like'),
        (TYPE_COMMENT, 'Comment'),
        (TYPE_FRIEND_REQUEST, 'Friend Request'),
    ]

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='sent_notifications', on_delete=models.CASCADE)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='notifications', on_delete=models.CASCADE)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    
    # Optional: Not all notifications are about a post (e.g. Friend Request)
    post = models.ForeignKey(Post, null=True, blank=True, on_delete=models.CASCADE)
    
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at'] # Newest first

    def __str__(self):
        return f'{self.sender} -> {self.recipient}: {self.type}'

# --- NEW: Signals (Automatic Triggers) ---

@receiver(post_save, sender=Like)
def create_like_notification(sender, instance, created, **kwargs):
    if created:
        # Don't notify if you like your own post
        if instance.user != instance.post.author:
            Notification.objects.create(
                sender=instance.user,
                recipient=instance.post.author,
                type=Notification.TYPE_LIKE,
                post=instance.post
            )

@receiver(post_save, sender=Comment)
def create_comment_notification(sender, instance, created, **kwargs):
    if created:
        if instance.author != instance.post.author:
            Notification.objects.create(
                sender=instance.author,
                recipient=instance.post.author,
                type=Notification.TYPE_COMMENT,
                post=instance.post
            )

@receiver(post_save, sender=Friendship)
def create_friend_request_notification(sender, instance, created, **kwargs):
    if created and instance.status == Friendship.STATUS_PENDING:
        Notification.objects.create(
            sender=instance.from_user,
            recipient=instance.to_user,
            type=Notification.TYPE_FRIEND_REQUEST
        )
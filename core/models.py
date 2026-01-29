from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.gis.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


# =========================
# User Model
# =========================

class User(AbstractUser):
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

# =========================
# Post Media Model
# =========================

class PostMedia(models.Model):
    MEDIA_TYPES = (
        ('image', 'Image'),
        ('video', 'Video'),
    )
    # Links to Post. related_name='media' lets us access post.media.all()
    post = models.ForeignKey('Post', related_name='media', on_delete=models.CASCADE)
    file = models.FileField(upload_to='post_media/')
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPES, default='image')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Media for Post {self.post.id}"

# =========================
# Post Model
# =========================

class Post(models.Model):

    # 1. Privacy Choices
    class Visibility(models.TextChoices):
        PUBLIC = 'public', 'Public'
        FRIENDS = 'friends', 'Friends Only'
        PRIVATE = 'private', 'Only Me'

    # 2. Location Choices
    class LocationAccess(models.TextChoices):
        ANYWHERE = 'anywhere', 'Anywhere'
        NEARBY = 'nearby', 'Nearby Only (500m)'

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    caption = models.TextField()
    
    location = models.PointField(
        srid=4326,
        null=True,
        blank=True
    )

    # 3. Privacy & Location Fields
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PUBLIC
    )
    location_access = models.CharField(
        max_length=10,
        choices=LocationAccess.choices,
        default=LocationAccess.ANYWHERE
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Post by {self.author.username} ({self.get_visibility_display()})'


# =========================
# Comment Model
# =========================

class Comment(models.Model):
    post = models.ForeignKey(
        Post,
        related_name='comments',
        on_delete=models.CASCADE
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    # --- NEW FIELDS FOR SPRINT 1 ---
    # 1. Parent: Links to another comment (Self-Referential)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        related_name='replies',
        on_delete=models.CASCADE
    )
    
    # 2. Likes: Users who liked this comment
    likes = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='liked_comments',
        blank=True
    )

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'Comment by {self.author.username} on {self.post}'
    
    @property
    def like_count(self):
        return self.likes.count()


# =========================
# Like Model
# =========================

class Like(models.Model):
    post = models.ForeignKey(
        Post,
        related_name='likes',
        on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'user')

    def __str__(self):
        return f'{self.user.username} likes {self.post}'


# =========================
# Friendship Model
# =========================

class Friendship(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_ACCEPTED = 'accepted'
    STATUS_DECLINED = 'declined'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_DECLINED, 'Declined'),
    ]

    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='friendship_requests_sent',
        on_delete=models.CASCADE
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='friendship_requests_received',
        on_delete=models.CASCADE
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('from_user', 'to_user')

    def __str__(self):
        return (
            f'Request from {self.from_user.username} '
            f'to {self.to_user.username} - {self.get_status_display()}'
        )


# =========================
# Notification Model
# =========================

class Notification(models.Model):
    TYPE_LIKE = 'like'
    TYPE_COMMENT = 'comment'
    TYPE_FRIEND_REQUEST = 'friend_request'

    TYPE_CHOICES = [
        (TYPE_LIKE, 'Like'),
        (TYPE_COMMENT, 'Comment'),
        (TYPE_FRIEND_REQUEST, 'Friend Request'),
    ]

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='sent_notifications',
        on_delete=models.CASCADE
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='notifications',
        on_delete=models.CASCADE
    )
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES
    )
    post = models.ForeignKey(
        Post,
        null=True,
        blank=True,
        on_delete=models.CASCADE
    )

    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.sender} -> {self.recipient}: {self.type}'


# =========================
# Signals
# =========================

@receiver(post_save, sender=Like)
def create_like_notification(sender, instance, created, **kwargs):
    if created and instance.user != instance.post.author:
        Notification.objects.create(
            sender=instance.user,
            recipient=instance.post.author,
            type=Notification.TYPE_LIKE,
            post=instance.post
        )


@receiver(post_save, sender=Comment)
def create_comment_notification(sender, instance, created, **kwargs):
    if created:
        # Scenario A: It is a Reply
        if instance.parent:
            # Notify the author of the parent comment
            if instance.author != instance.parent.author:
                Notification.objects.create(
                    sender=instance.author,
                    recipient=instance.parent.author,
                    type=Notification.TYPE_COMMENT,
                    post=instance.post # Links back to main post
                )
        
        # Scenario B: It is a Top-Level Comment
        else:
            # Notify the Post Author
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

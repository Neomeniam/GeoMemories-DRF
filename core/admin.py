from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from .models import User, Post, Comment, Like, Friendship

admin.site.unregister(Group)

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Profile Info', {'fields': ('avatar', 'bio')}),
    )

admin.site.register(Post)
admin.site.register(Comment)
admin.site.register(Like)
admin.site.register(Friendship)

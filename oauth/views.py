from django.utils import timezone
from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import PostStatus, UserProfile
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage

class HomeView(View):
    def get(self, request):
        return render(request, 'home.html')

class SignupView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return render(request, 'signup.html')

    def post(self, request):
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists")
            return redirect('signup')

        if password1 != password2:
            messages.error(request, "Passwords don't match")
            return redirect('signup')

        try:
            validate_password(password1)
            user = User.objects.create_user(username=email, email=email, password=password1)
            UserProfile.objects.create(user=user, email=email, name=email)
            auth_login(request, user)
            return redirect('dashboard')
        except ValidationError as e:
            messages.error(request, e.messages[0])
            return redirect('signup')

class LoginView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return render(request, 'login.html')

    def post(self, request):    
        user = authenticate(
            request,
            username=request.POST.get('email'),
            password=request.POST.get('password')
        )
        if user:
            auth_login(request, user)
            return redirect('dashboard')
        messages.error(request, "Invalid email or password")
        return redirect('login')

class LogoutView(View):
    def get(self, request):
        return render(request, "signout.html")
    def post(self, request):
        auth_logout(request)
        return redirect('login')

class RecentPostsView(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('login')

        user_profile = UserProfile.objects.get(user=request.user)
        
        # Get filter parameters
        platform = request.GET.get('platform', '')
        date_range = request.GET.get('date_range', '')
        status = request.GET.get('status', '')  # Add status filter parameter
        
        # Start with all user posts
        posts_query = PostStatus.objects.filter(user=user_profile)
        
        # Apply platform filter
        if platform:
            posts_query = posts_query.filter(platform=platform)
            
        # Apply date filter
        if date_range:
            today = timezone.now().date()
            if date_range == 'today':
                posts_query = posts_query.filter(created_at__date=today)
            elif date_range == 'week':
                start_of_week = today - timezone.timedelta(days=today.weekday())
                posts_query = posts_query.filter(created_at__date__gte=start_of_week)
            elif date_range == 'month':
                posts_query = posts_query.filter(
                    created_at__year=today.year,
                    created_at__month=today.month
                )
        
        # Apply status filter
        if status:
            posts_query = posts_query.filter(status=status)
        
        # Order by most recent first
        recent_posts = posts_query.order_by('-created_at')
        
        # Pagination
        paginator = Paginator(recent_posts, 10)  
        page = request.GET.get('page', 1)  # Default to first page

        try:
            paginated_posts = paginator.page(page)
        except PageNotAnInteger:
            paginated_posts = paginator.page(1)
        except EmptyPage:
            paginated_posts = paginator.page(paginator.num_pages)

        return render(request, "recent_posts.html", {
            "recent_posts": paginated_posts,
            "selected_platform": platform,
            "selected_date_range": date_range,
            "selected_status": status,  # Add this to pass to template
            "is_paginated": paginated_posts.has_other_pages()
        })
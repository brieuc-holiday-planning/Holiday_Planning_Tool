from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.contrib.auth.views import LoginView

from .models import User


class HolidayLoginView(LoginView):
    template_name = "accounts/login.html"


@login_required
def landing(request):
    """Post-login dispatcher: sends each user to the page most relevant to
    their day-to-day use of the tool.

    An admin (see User.is_scrum_master) is also often a team member who
    submits their own holiday requests, so - unlike Chapter Lead/End User,
    who have exactly one obvious destination - they get an actual landing
    page with links to both the admin and (if they belong to a squad) the
    request-submission calendar, rather than being redirected straight
    into /admin/ with no way back into the rest of the app (the admin site
    doesn't render our app's nav).
    """
    user = request.user
    if user.is_scrum_master:
        if not user.squad_id:
            return redirect("admin:index")
        return render(request, "accounts/landing.html", {})
    if user.role == User.Role.CHAPTER_LEAD:
        return redirect("holidays:approval_inbox")
    if user.squad_id:
        return redirect("holidays:squad_calendar", squad_id=user.squad_id)
    return redirect("admin:index")

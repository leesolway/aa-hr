from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook
from django.utils.translation import gettext_lazy as _

from . import urls as hr_urls


@hooks.register("url_hook")
def register_urls():
    return UrlHook(hr_urls, "hr", r"^hr/")


class HrMenu(MenuItemHook):
    def __init__(self):
        MenuItemHook.__init__(
            self,
            _("HR"),
            "fa-solid fa-id-card",
            "hr:index",
            navactive=["hr:index"],
        )

    def render(self, request):
        if request.user.has_perm("hr.access_hr"):
            return MenuItemHook.render(self, request)
        return ""


@hooks.register("menu_item_hook")
def register_hr_menu():
    return HrMenu()

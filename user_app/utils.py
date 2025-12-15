from bioblend.galaxy import GalaxyInstance
from django.conf import settings

def validar_api_key(api_key: str) -> bool:
    try:
        gi = GalaxyInstance(url=settings.GALAXY_URL, key=api_key)
        gi.users.get_current_user()
        return True
    except Exception:
        return False

from . import models
from . import controllers
from . import wizards


def _create_default_social_media(env):
    companies = env['res.company'].with_context(active_test=False).search([])
    company_need_create_social_media = companies - env['social.media'].sudo().search([('social_provider', '=', 'facebook')]).company_id
    company_need_create_social_media._create_default_social_media()


def post_init_hook(env):
    _create_default_social_media(env)

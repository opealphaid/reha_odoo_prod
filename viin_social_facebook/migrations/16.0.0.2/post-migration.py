from odoo import api, SUPERUSER_ID


def _create_media_for_company(cr):
    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env['res.company'].with_context(active_test=False).search([])
    company_need_create_social_media = companies - env['social.media'].sudo().search(
        [('social_provider', '=', 'facebook')]).company_id
    company_need_create_social_media._create_default_social_media()


def _update_company_for_post(cr):
    query = """
    update social_post
    set company_id = sp.company_id
    from social_page sp where sp.id = social_post.page_id
    """
    cr.execute(query)


def _update_company_for_notice(cr):
    query = """
    UPDATE social_notice
    SET company_id =
    CASE
    WHEN post_id IS NOT NULL THEN (SELECT company_id FROM social_post WHERE social_post.id = social_notice.post_id)
    ELSE (SELECT company_id FROM social_page WHERE social_page.id = social_notice.page_id)
    END;
    """
    cr.execute(query)


def migrate(cr, version):
    _create_media_for_company(cr)
    _update_company_for_post(cr)
    _update_company_for_notice(cr)

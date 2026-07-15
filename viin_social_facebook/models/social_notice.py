from odoo import models, api


class SocialNotice(models.Model):
    _inherit = 'social.notice'

    @api.depends('page_id.social_provider')
    def _compute_post_link(self):
        return super(SocialNotice, self)._compute_post_link()

    def _get_post_link(self):
        self.ensure_one()
        if self.page_id.social_provider == 'facebook' and self.social_post_id:
            return 'https://facebook.com/%s' % self.social_post_id
        return super(SocialNotice, self)._get_post_link()

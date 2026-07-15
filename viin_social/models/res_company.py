from odoo import api, models, fields


class Company(models.Model):
    _inherit = 'res.company'

    receive_comment_notification = fields.Boolean(string='Receive Comment Notification', default=True,
                                                  help="Receive comment notifications from social networks")
    receive_reactive_notification = fields.Boolean(string='Receive Reactive Notification', default=False,
                                                   help="Receive notifications of post reactions from social networks")

    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        res._create_default_social_media()
        return res

    def _prepare_social_media_vals(self):
        """ Function for inheriting social media modules and adding data for creating media for the company"""
        self.ensure_one()
        return []

    def _create_default_social_media(self):
        """ Create media when creating company """
        vals = []
        # sudo() get all media of companies is not permission
        all_medias = self.env['social.media'].sudo().search([])
        for r in self:
            media_vals = r._prepare_social_media_vals()
            medias = all_medias.filtered(lambda media: media.company_id.id == r.id)
            media_vals = [media for media in media_vals if media.get('name', False) not in medias.mapped('name')]
            vals += media_vals
        if vals:
            self.env['social.media'].sudo().create(vals)

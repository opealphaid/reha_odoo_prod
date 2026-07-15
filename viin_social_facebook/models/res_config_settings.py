from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    facebook_app_id = fields.Char(string='Facebook App ID', related='company_id.facebook_app_id', readonly=False)
    facebook_client_secret = fields.Char(string='Facebook Client Secret', related='company_id.facebook_client_secret', readonly=False)

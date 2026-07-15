import base64

from odoo import models, fields
from odoo.modules.module import file_path


class ResCompany(models.Model):
    _inherit = 'res.company'

    facebook_app_id = fields.Char(string='Facebook App ID')
    facebook_client_secret = fields.Char(string='Facebook Client Secret')

    def _prepare_social_media_vals(self):
        res = super(ResCompany, self)._prepare_social_media_vals()
        image_path = file_path('viin_social_facebook/static/img/facebook.png')
        image = base64.b64encode(open(image_path, 'rb').read())
        res.append({
            'company_id': self.id,
            'social_provider': 'facebook',
            'name': 'Facebook',
            'description': 'Manage your Facebook pages and posts',
            'image': image,
        })
        return res

import requests
from odoo import models


class SocialFacebookApi(models.AbstractModel):
    _name = 'social.facebook.api'
    _inherit = 'social.mixin'
    _description = 'Social Facebook Api'

    def get_page_info(self, page_id, access_token):
        url = 'https://graph.facebook.com/%s?fields=engagement,fan_count&access_token=%s' % (page_id, access_token)
        res = requests.get(url)
        self.raise_http_error(res, url)
        return res.json()

    def get_page_total_like(self, page_id, access_token):
        return self.get_page_info(page_id, access_token).get('fan_count', 0)

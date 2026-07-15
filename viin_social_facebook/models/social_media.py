import requests
from datetime import datetime, timedelta

from odoo import models, fields, _
from odoo.exceptions import UserError
from odoo.http import request


host = "https://graph.facebook.com"
authorize = "https://graph.facebook.com/oauth/authorize"
oauth_access_token = "https://graph.facebook.com/v24.0/oauth/access_token"
scope = "&scope=public_profile,email,pages_manage_posts,pages_manage_metadata,pages_manage_engagement,publish_video,pages_messaging"
"""
Requied:
1. pages_manage_posts
    - pages_show_list
    - pages_read_engagement
2. pages_manage_engagement
    - pages_show_list
    - pages_read_user_content
3. pages_manage_metadata
    - pages_show_list
"""


class SocialMedia(models.Model):
    _inherit = 'social.media'

    social_provider = fields.Selection(selection_add=[('facebook', 'Facebook')], ondelete={'facebook': 'set default'})
    facebook_user_id = fields.Char(string="User Id of Facebook", readonly=True)
    facebook_access_token = fields.Text(string="Facebook Access Token", readonly=True)

    def action_link_account(self):
        self.ensure_one()
        request.session['social_media_id'] = self.id
        domain = self.get_base_url().split("//")[1]
        if self.social_provider == 'facebook':
            response_type = "?response_type=code"
            client_id = "&client_id=%s" % (self.company_id.facebook_app_id)
            redirect_uri = "&redirect_uri=https://%s/facebook_callback_user_access_token" % domain
            url = authorize + response_type + client_id + redirect_uri + scope
            return {
                'type': 'ir.actions.act_url',
                'url': url,
                'target': 'new'
            }
        else:
            return super(SocialMedia, self).action_link_account()

    def action_synchronized(self):
        self.ensure_one()
        if self.social_provider == 'facebook' and not self.facebook_user_id and not self.facebook_access_token:
            raise UserError(_("Cannot sync because Facebook User Id or Facebook Access Token has no value."))
        return super(SocialMedia, self).action_synchronized()

    def _synchronized(self):
        """ Synchronize data pages from Facebook """
        self.ensure_one()
        if self.social_provider != 'facebook':
            return super(SocialMedia, self)._synchronized()

        url = host + "/%s/accounts?fields=id,name,about,description,picture,fan_count,access_token&access_token=%s" \
                     % (self.facebook_user_id, self.facebook_access_token)
        res = requests.get(url)
        self.raise_http_error(res, url)
        data_dict_json = res.json()

        page_list = data_dict_json.get('data', False)
        if page_list:
            for page in page_list:
                page.update({
                    'like_count': self.env['social.facebook.api'].get_page_total_like(page['id'], self.facebook_access_token)
                })
            self.env['social.page'].with_context(media_id=self.id)._update_facebook_page_list(page_list, self.id)

        self.env['social.page'].search([('social_provider', '=', 'facebook')])._check_page_subscribed_apps()
        return super(SocialMedia, self)._synchronized()

    def _fb_exchange_code(self, fb_exchange_code):
        """
        Convert code to Convert Short-lived Token
        """
        if fb_exchange_code:
            client_id = "?client_id=%s" % self.company_id.facebook_app_id
            client_secret = "&client_secret=%s" % self.company_id.facebook_client_secret
            domain = self.get_base_url().split("//")[1]
            redirect_uri = "&redirect_uri=https://%s/facebook_callback_user_access_token" % domain
            code = "&code=%s" % fb_exchange_code
            url = oauth_access_token + client_id + client_secret + redirect_uri + code

            res = requests.get(url)
            self.raise_http_error(res, url)
            data = res.json()

            access_token = data.get('access_token', False)
            if access_token:
                self._fb_exchange_token(access_token)

    def _fb_exchange_token(self, fb_exchange_token):
        """
        Convert Short-lived Token to Long-lived Token
        """
        if not fb_exchange_token:
            raise UserError(_("Short-lived Token is missing, please enter this field"))

        client_id = self.company_id.facebook_app_id
        client_secret = self.company_id.facebook_client_secret

        url1 = host + '/me?access_token=%s' % fb_exchange_token
        res = requests.get(url1)
        self.raise_http_error(res, url1)
        user = res.json()

        user_id = user.get('id', False)
        url2 = host + '/oauth/access_token?grant_type=fb_exchange_token&client_id=%s&client_secret=%s&fb_exchange_token=%s' \
                      % (client_id, client_secret, fb_exchange_token)
        res = requests.get(url2)
        self.raise_http_error(res, url2)
        data_dict_json = res.json()

        if data_dict_json.get('token_type', False) == 'bearer':
            expires_in = 5180000  # ~60 days
            date_end = datetime.now() + timedelta(seconds=expires_in)
            self.write({
                'facebook_user_id': user_id,
                'facebook_access_token': data_dict_json.get('access_token', False),
                'token_expired_date': date_end
            })

    def _cron_synchronized_all_datas_facebook(self):
        for r in self:
            if not r.facebook_user_id or not r.facebook_access_token:
                continue
            r._synchronized()

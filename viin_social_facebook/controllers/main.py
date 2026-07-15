import hmac
import hashlib
import threading
import werkzeug.utils
from datetime import datetime

from odoo import http
from odoo.http import request, Response


class MainController(http.Controller):

    @http.route('/facebook_callback_user_access_token', type='http', auth='public')
    def get_access_token(self, **kwargs):
        code = kwargs.get('code', False)
        if code:
            try:
                if not request.session.get('social_media_id', False):
                    return
                Media = request.env['social.media'].browse(request.session.get('social_media_id'))
                Media._fb_exchange_code(code)
                Media._synchronized()
                url = '/web#action=%s' % request.env.ref('viin_social.social_page_action').id
                request.session.pop('social_media_id')
                return werkzeug.utils.redirect(url)
            except Exception as e:
                return str(e)
        else:
            return "Error: 'code' not found in request <br>Parameters:<br> %s" % kwargs

    # Webhooks : verification for page posts
    @http.route('/facebook_webhooks', type='http', auth='public', methods=['GET'])
    def get_verification_requests(self, **kwargs):
        token = request.env['ir.config_parameter'].sudo().get_param('viin_social_facebook.facebook_webhook_token', 'viindoo2019')
        if kwargs.get('hub.verify_token', "") == token:
            challenge = kwargs.get('hub.challenge', False)
            if challenge:
                return Response(challenge, status=200)

    # """
    #     Webhooks:
    #     -Receive notifications and sync posts when there are actions:
    #         - comments,
    #         - reaction (like, haha, wow, ...)
    #         - delete post
    #         - share : if include page post and link attachment.
    #         ---------
    #         Others: development later
    #             * post as page:
    #                 - If not in the system, get information of this 1 post  and create a post on system
    #                 - else pass
    #             * user posts on the page: <Currently, the user is not allowed to post to the page>
    # """
    @http.route('/facebook_webhooks', type='json', auth='public', methods=['POST'])
    def get_data_webhooks(self):
        fb_signature = request.httprequest.headers.get('X-Hub-Signature')[5:]
        expected_signatures = []
        companies = request.env['res.company'].sudo().search([('facebook_client_secret', '!=', False)])
        for company in companies:
            expected_signatures.append(hmac.new(company.facebook_client_secret.encode(), request.httprequest.data, hashlib.sha1).hexdigest())
        if fb_signature not in expected_signatures:
            return Response(status=404)

        data = request.get_json_data()
        if data:
            entry = data.get('entry', [False])[0]
            if entry:
                changes = entry.get('changes', False)
                messaging = entry.get('messaging', False)

                # Because facebook needs us to return 200 response if we have successfully received data
                # after 2 seconds max, but the action below takes a while.
                # So here we need to create a separate thread to process data.
                if messaging:
                    threading.Thread(target=self._process_data_fb_webhook, args=('_process_messaging', request.env, entry)).start()
                if changes:
                    threading.Thread(target=self._process_data_fb_webhook, args=('_process_changes', request.env, entry)).start()

        return Response(status=200)

    def _process_data_fb_webhook(self, method, env, *args, **kwargs):
        with env['base'].pool.cursor() as cr:
            getattr(self, method)(env(cr=cr), *args, **kwargs)

    def _process_messaging(self, env, entry):
        messaging = entry.get('messaging', [False])[0]
        if messaging:
            social_page_id = entry.get('id', False)

            # Maybe multiple pages, because multiple companies
            pages = env['social.page'].sudo().search([('social_page_id', '=', social_page_id)])

            for page in pages:
                group_approve = env.ref('viin_social.viin_social_group_admin', raise_if_not_found=False)
                group_approve = group_approve and [group_approve.id] or []
                defaul_user = env['res.users'].sudo().search([('groups_id.id', 'in', group_approve),
                                                              ('company_id', '=', page.company_id.id)], limit=1)
                page.with_user(defaul_user).with_context(check_group=False)._get_social_page_message()

    def _process_changes(self, env, entry):
        value = entry.get('changes', [''])[0].get('value', False)
        if value:
            Post = env['social.post'].sudo()

            social_page_id = entry.get('id', False)
            time = datetime.fromtimestamp(entry['time'])
            action_type = value.get('item', '')
            social_post_id = value.get('post_id', False)

            if action_type == 'share':
                if 'permalink.php' in value.get('link', ''):
                    post_page = value['link'].split("story_fbid=")[1].split("&id=")
                    social_post_id = post_page[0]
                    social_page_id = post_page[1]
                return
            elif action_type == 'comment' and value.get('verb', '') == 'add':
                check = value.get('post', {}).get('promotion_status', '')
                if check in ('ineligible', 'inactive'):  # recheck : ineligible / inactive ??
                    # notice type : 'comment'
                    notice_vals = {
                        'social_post_id': social_post_id,
                        'social_page_id': social_page_id,
                        'post_id': False,
                        'page_id': False,
                        'type': 'comment',
                        'social_message': value.get('message', False),
                        'social_comment_id': value.get('comment_id', False),
                        'social_user_id': value.get('from', {}).get('id', False),
                        'social_user_name': value.get('from', {}).get('name', False),
                        'social_time': time,
                        'photo': value.get('photo', False)
                    }
                    env['social.notice'].sudo()._create_notice([notice_vals])
            elif action_type == 'reaction' and value.get('verb', '') == 'add':
                notice_vals = {
                    'social_post_id': social_post_id,
                    'social_page_id': social_page_id,
                    'type': 'reaction',
                    'social_user_id': value.get('from', {}).get('id', False),
                    'social_user_name': value.get('from', {}).get('name', False),
                    'social_time': time,
                    'reaction_type': value.get('reaction_type', False)
                }
                env['social.notice'].sudo()._create_notice([notice_vals])
            elif action_type == 'post':
                if value.get('verb', '') == 'remove' and social_post_id:
                    Post.search([('social_post_id', '=', social_post_id)]).unlink()
                return

            # synchronize 1 post-page
            if social_page_id and social_post_id:
                Post._update_post_from_notice(social_post_id)

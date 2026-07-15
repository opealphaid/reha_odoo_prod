import requests
import logging

from datetime import datetime
from dateutil.parser import parse


from odoo import models, fields, api, SUPERUSER_ID, _
from odoo.exceptions import AccessError
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)
host = "https://graph.facebook.com"


class SocialPage(models.Model):
    _inherit = 'social.page'

    facebook_page_about = fields.Char(string=" About Facebook Page", readonly=True)
    facebook_page_access_token = fields.Text(string="Access Token", help="Access Token of Facebook Page", readonly=True)
    review_ids = fields.One2many('social.review', 'page_id', string='All Reviews')

    # The 2 fields used to optionally sync the page's posts
    sync_all_post = fields.Boolean(string="Sync all posts", default=False,
                                   help="By default, the 100 most recent posts will be synced. "
                                   "If this field is checked, all posts will be synchronized.\n"
                                   "The sync will be processed in batches of up to 500 posts at a time "
                                   "via daily 'Scheduled Actions' or the buton 'Synchronize Old Posts'.")
    next_post_sync_url = fields.Text(help="Technical field, Used to save the URL of the next synchronization, "
                                     "avoiding calling it once causing an API limit exceeded error.\n"
                                     "This URL will sync with the next 500 posts following the last synced post.")

    # This fields used to request permission to access `pages_manage_metadata` from the Facebook API
    # Page Setting Docs: https://developers.facebook.com/docs/graph-api/reference/page/settings
    users_can_message = fields.Boolean(string='Users Can Message',
        help="If checked, people can message this Page via a message button")
    # users_can_post = fields.Boolean(string='Users Can Post?',
    #     help="If checked, people can post to this Page's timeline")
    # users_can_post_photos = fields.Boolean(string='Users Can Post Photos?',
    #     help="If checked, people can post photos and videos to this Page")
    users_can_tag_photos = fields.Boolean(string='Users Can Tag Photos',
        help="If checked, people who like this page can tag people in photos posted by this Page")
    review_posts_by_other = fields.Boolean(string='Review Post By Other',
        help="If checked, posts by others are hidden by default. If false, posts are visible by default")
    profanity_filter = fields.Selection(
        [('Off', 'Off'),
         ('Medium', 'Medium'),
         ('Strong', 'Strong')],
        string='Profanity Filter', default='Strong', required=True,
        help="If checked, If the option is set to any valid values, prevent profanity on this Page based on the level")
    is_published = fields.Boolean(string='Is Published',
        help="If checked, it means that page is published. If value is false, page is unpublished.")
    # More: https://developers.facebook.com/docs/graph-api/reference/page/subscribed_apps
    subscribed_apps = fields.Char(string="Subscribed Apps", readonly=True,
        help="Setting technical, don't change if you don't known this information.")

    # This function used to request permission to access `pages_manage_metadata` from the Facebook API
    @api.onchange('users_can_message', 'review_posts_by_other',
                  # 'users_can_post', 'users_can_post_photos',
                  'users_can_tag_photos', 'profanity_filter',
                  'is_published')
    def _onchange_setting(self):
        option = ''
        page_old = self._origin
        if page_old.users_can_message != self.users_can_message:
            option = '{USERS_CAN_MESSAGE: true}' if self.users_can_message else '{USERS_CAN_MESSAGE: false}'
        # elif page_old.users_can_post != self.users_can_post:
        #     option = '{USERS_CAN_POST: true}' if self.users_can_post else '{USERS_CAN_POST: false}'
        # elif page_old.users_can_post_photos != self.users_can_post_photos:
        #     option = '{USERS_CAN_POST_PHOTOS: true}' if self.users_can_post_photos else '{USERS_CAN_POST_PHOTOS: false}'
        elif page_old.review_posts_by_other != self.review_posts_by_other:
            option = '{REVIEW_POSTS_BY_OTHER: true}' if self.review_posts_by_other else '{REVIEW_POSTS_BY_OTHER: false}'
        elif page_old.users_can_tag_photos != self.users_can_tag_photos:
            option = '{USERS_CAN_TAG_PHOTOS: true}' if self.users_can_tag_photos else '{USERS_CAN_TAG_PHOTOS: false}'
        elif page_old.profanity_filter != self.profanity_filter:
            option = "{PROFANITY_FILTER: '%s'}" % (self.profanity_filter)
        else:
            option = '{IS_PUBLISHED: true}' if self.is_published else '{IS_PUBLISHED: false}'

        url = host + '/%s/settings?option=%s&access_token=%s' % (self.social_page_id, option, self.facebook_page_access_token)
        req = requests.post(url)
        success = True
        try:
            req.raise_for_status()
        except Exception as e:
            success = False
            _logger.error(str(e))

        if not success:
            raise UserError(_('Setup failed: An error has occurred, please contact your administrator for help.\nError code: %(status_code)s\n%(error)s') % {
                'status_code': req.status_code,
                'error': req.json(),
            })

        return {
            'warning': {
                'title': _('Notice'),
                'message': _('Update Page Setting Success')
            }
        }

    # This function used to request permission to access `pages_manage_metadata` from the Facebook API
    def action_subscrib_app(self):
        self._check_page_subscribed_apps()

    def action_refresh_reviews(self):
        self.env['social.review']._get_all_reivews(self.id, self.social_page_id, self.facebook_page_access_token)

    def action_view_all_reviews(self):
        url = 'https://www.facebook.com/%s/reviews' % (self.social_page_id)
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new'
        }

    def action_sinchronized_posts(self):
        self.ensure_one()
        if self.media_id.social_provider != 'facebook':
            return super(SocialPage, self).action_sinchronized_posts()

        url = host + "/%s/feed?fields=message,from,created_time,permalink_url,likes.summary(1),shares,comments.summary(1)," \
                     "attachments{media,subattachments.limit(1000)}&limit=100&access_token=%s" \
                     % (self.social_page_id, self.facebook_page_access_token)

        number_paging = 1 if not self.sync_all_post else 5
        self._synchronized_posts_facebook(url, number_paging)
        self.notify(_('Post sync successful!'))

    def _synchronized_posts_facebook(self, url, number_paging):
        self.ensure_one()
        actual_post_list = []
        while number_paging > 0:
            res = requests.get(url)
            self.raise_http_error(res, url)
            data = res.json()

            post_list = data.get('data', False)

            if post_list:
                for post in post_list:
                    is_author = self._check_author_post(post, self.social_page_id)
                    if not post.get('is_schesdule_later', False) and is_author:
                        total_likes = post.get('likes', {}).get('summary', {}).get('total_count', False)
                        total_comments = post.get('comments', {}).get('summary', {}).get('total_count', False)
                        total_shares = post.get('shares', {}).get('count', False)
                        more_data = {
                            'total_likes': total_likes,
                            'total_comments': total_comments,
                            'total_shares': total_shares,
                        }
                        post.update(more_data)
                        actual_post_list.append(post)

            next_url = data.get('paging', {}).get('next', False)
            if next_url:
                url = next_url
                number_paging -= 1
            else:
                break
        actual_post_list += self._synchronize_scheduled_post()
        inactive_post = self._context.get('inactive_post', True)
        self.env['social.post'].with_context(page_id=self.id, inactive_post=inactive_post)._update_facebook_post_list(actual_post_list, self.id)
        self.write({'next_post_sync_url': next_url})

    def action_sinchronized_page(self):
        self.ensure_one()
        if self.media_id.social_provider != 'facebook':
            return super(SocialPage, self).action_sinchronized_page()

        if self.env.user.has_group('viin_social.viin_social_group_editor'):
            self.media_id.sudo()._synchronized()
        else:
            raise AccessError(_("You have no rights to this action."))
        return super(SocialPage, self).action_sinchronized_page()

    def _update_facebook_page_list(self, page_list, media_id):
        social_pages = self.env['social.page'].with_context(active_test=False).search([('media_id', '=', media_id)])
        social_page_ids = social_pages.mapped('social_page_id')

        page_ids_new = []
        page_ids_update = []
        page_ids_create = []
        for page in page_list:
            page_ids_new.append(page['id'])
            data = self._prepare_facebook_page_data(page)
            if page['id'] not in social_page_ids:
                data['media_id'] = self._context.get('media_id', False)
                page_ids_create.append(data)
            else:
                data['active'] = True
                page_ids_update.append(data)

        # Page list for Create
        if page_ids_create:
            self.env['social.page'].create(page_ids_create)

        # Page list for Update
        for page in page_ids_update:
            page_update = social_pages.filtered(lambda r: r.social_page_id == page['social_page_id'])
            if page_update:
                page_update.write(page)

        # Page list for Inactive
        pages_for_inactive = social_pages.filtered(lambda r: r.social_page_id not in page_ids_new)
        if pages_for_inactive:
            pages_for_inactive.write({'active': False})

    def _get_timestamp(self, days):
        timestamp = int(datetime.timestamp(datetime.now()))
        timestamp_ago = timestamp - days * 24 * 60 * 60
        return timestamp_ago, timestamp

    def _prepare_facebook_page_data(self, page):
        image = self._read_image_from_url(page['picture']['data']['url'])
        return {
            'social_page_id': page['id'],
            'name': page['name'],
            'description': page.get('description', False),
            'follower_count': page.get('fan_count', False),
            'facebook_page_about': page.get('about', False),
            'facebook_page_access_token': page['access_token'],
            'social_provider': 'facebook',
            'social_page_url': "https://www.facebook.com/%s" % (page['id']),
            'image': image,
            'like_count': page['like_count']
        }

    def _synchronize_scheduled_post(self):
        url = host + "/%s/scheduled_posts?fields=message,created_time,permalink_url,shares,attachments&limit=100&access_token=%s" \
                     % (self.social_page_id, self.facebook_page_access_token)
        res = requests.get(url)
        self.raise_http_error(res, url)
        data_dict_json = res.json()

        post_list = data_dict_json.get('data', [])
        for post in post_list:
            post.update({'is_schesdule_later': True})
        return post_list

    # """
    #     Webhooks : auto check when synchronize all pages
    #     check page has registered for notification yet
    #      If not, then register for each page
    #         - feed : Describes nearly all changes to a Page's feed, such as Posts, shares, likes, etc.
    #             *https://developers.facebook.com/docs/graph-api/webhooks/reference/page/#feed
    #         - mention : Describes new mentions of a page, including mentions in comments, posts, etc.
    #                     Some comment_id and post_id fields returned in mention webhooks may not be queried due to missing permissions including privacy issues.
    #             *https://developers.facebook.com/docs/graph-api/webhooks/reference/page/#mention
    # """
    def _check_page_subscribed_apps(self):
        pages_to_subscribed = self.env['social.page']
        for r in self:
            url = host + "/%s/subscribed_apps?access_token=%s" % (r.social_page_id, r.facebook_page_access_token)
            res = requests.get(url)
            self.raise_http_error(res, url)
            data_list = res.json().get('data', [])

            for data in data_list:
                if data.get('id', '') == r.company_id.facebook_app_id:
                    fields = data.get('subscribed_fields', [])
                    if set(fields) >= {'feed', 'messages', 'message_mention'}:
                        pages_to_subscribed |= r
        if pages_to_subscribed:
            pages_to_subscribed._page_subscrib_apps()
        self.write({'subscribed_apps': 'feed,messages,message_mention'})

    # https://developers.facebook.com/docs/graph-api/reference/page/subscribed_apps/#Reading
    def _page_subscrib_apps(self):
        for r in self:
            url = host + "/%s/subscribed_apps?subscribed_fields=messages,message_mention,feed&access_token=%s" \
                         % (r.social_page_id, r.facebook_page_access_token)
            res = requests.post(url)
            self.raise_http_error(res, url)

    # This function used to request permission to access `pages_manage_metadata` from the Facebook API
    def action_cacncel_subscrib_app_facebook(self):
        for r in self:
            url = host + "/%s/subscribed_apps?access_token=%s" % (r.social_page_id, r.facebook_page_access_token)
            res = requests.delete(url)
            self.raise_http_error(res, url)
            r.write({'subscribed_apps': False})

    def _prepare_social_message_facebook_data(self, messages, old_conversation=False):
        if old_conversation:
            old_messages = old_conversation.message_ids

        page_id = self.social_page_id
        message_datas = []
        attachments = []
        old_attachments = self.env['ir.attachment']
        messages.reverse()
        subtype_id = self.env.ref('mail.mt_comment').id

        for message in messages:
            if message.get('message', False):
                message.update({'message': message['message'].replace('\n', '<br>')})

            old_message = False
            if old_conversation:
                old_message = old_messages.filtered(lambda m: m.social_message_id == message.get('id', False))
                old_message = old_message[0] if old_message else False
            if old_message and old_message.attachment_ids:
                old_attachments |= old_message.attachment_ids
            attachments = []
            message_attachments = message.get('attachments', False) and message.get('attachments', False).get('data', []) or []
            for attachment in message_attachments:
                attachment_url = attachment.get('image_data', {}).get('url', False) or \
                                 attachment.get('file_url', False) or \
                                 attachment.get('video_data', {}).get('url', False)
                attachment = (0, 0, {
                    'type': 'url',
                    'url': attachment_url,
                    'name': attachment.get('name', False),
                    'mimetype': attachment.get('mime_type', False)
                })
                attachments.append(attachment)
            sticker_url = message.get('sticker', False)
            if sticker_url:
                attachment = (0, 0, {
                    'type': 'url',
                    'url': sticker_url,
                    'name': 'social_sticker_facebook',
                    'mimetype': 'image/png'
                })
                attachments.append(attachment)
            message_data = {
                'social_message_id': message.get('id', False),
                'body': message.get('message', ''),
                'subtype_id': subtype_id,
                'attachment_ids': attachments,
                'model': 'discuss.channel'
            }
            author = message.get('from', False)
            if author and author.get('id', False) != page_id:
                message_data.update({
                    'author_id': False,
                    'email_from': author.get('name', 'abc@example.viindoo.com'),
                    })
            created_time = parse(message['created_time'])
            created_time = datetime.combine(created_time.date(), created_time.time())
            message_data.update({'date': created_time})
            if old_message:
                message_datas.append((1, old_message.id, message_data))
            else:
                message_data.update({
                    'message_type': 'comment'
                })
                message_datas.append((0, 0, message_data))
        if old_attachments:
            old_attachments.unlink()
        return message_datas

    def _prepare_social_conversation_facebook_data(self, conversation, old_conversation=False):
        self.ensure_one()
        participants = conversation.get('participants', {}).get('data', [])
        if len(participants) < 2:
            return {}
        conversation_data = {
            'channel_type': 'social_chat',
            'message_ids': self._prepare_social_message_facebook_data(messages=conversation.get('messages', {}).get('data', []), old_conversation=old_conversation),
            'social_conversation_id': conversation.get('id', False),
            'social_page_id': self.id
        }
        valid_partners = self.member_ids.partner_id
        channel_partners_to_create = valid_partners
        if old_conversation:
            last_seen_partners = old_conversation.channel_member_ids
            channel_partners_to_delete = last_seen_partners.filtered(lambda r: r.partner_id not in valid_partners)
            channel_partners_to_create = valid_partners - last_seen_partners.partner_id
            channel_partners_to_delete.unlink()
        default_members = []
        for partner in channel_partners_to_create:
            default_members.append((0, 0, {'partner_id': partner.id}))
        if default_members:
            conversation_data.update({'channel_member_ids': default_members})

        for participant in participants:
            if participant.get('id', False) != self.social_page_id:
                conversation_data.update({
                    'name': "[%s] %s" % (self.name, participant.get('name', 'Facebook User')),
                    'social_user_name': participant.get('name', 'Facebook User'),
                    'social_participant_id': participant.get('id', False),
                })
        return conversation_data

    def _get_social_page_message_facebook(self):
        """
        Synchronize the 25 most recent conversations
        """
        self.ensure_one()

        page_id = self.social_page_id
        page_access_token = self.facebook_page_access_token
        if not page_id or not page_access_token:
            return

        conversation_create_datas = []
        MailChannel = self.env['discuss.channel'].sudo()
        social_channels_to_update_imange = self.env['discuss.channel'].sudo()
        channels_re_show = self.env['discuss.channel'].sudo()
        old_conversations = MailChannel.search([('social_page_id', '=', self.id)])

        url = host + "/%s/conversations?fields=participants,messages.limit(500)" \
                     "{from,message,sticker,attachments,created_time}&access_token=%s" \
                     % (page_id, page_access_token)
        res = requests.get(url)
        self.raise_http_error(res, url)
        data_dict_json = res.json()

        data = data_dict_json.get('data', False)
        for conversation in data:
            old_conversation = old_conversations.filtered_domain(
                [('social_conversation_id', '=', conversation.get('id', False))])[:1]

            if old_conversation:
                channels_re_show |= old_conversation
                if not old_conversation.image_128:
                    social_channels_to_update_imange |= old_conversation

                # If the last message is already synchronized, skip it
                messages_data = conversation.get('messages', {}).get('data', [])
                if messages_data:
                    last_message_mid = messages_data[0].get('id', False)
                    if old_conversation.message_ids[:1].social_message_id == last_message_mid:
                        continue
                old_messages = old_conversation.message_ids
                conversation_data = self._prepare_social_conversation_facebook_data(conversation, old_conversation)
                if conversation_data:
                    old_conversation.with_user(SUPERUSER_ID).write(conversation_data)

                new_messages = old_conversation.message_ids - old_messages
                for msg in new_messages:
                    msg_vals = {
                        'author_id': self.with_user(SUPERUSER_ID)._message_compute_author()[0],
                        'body': msg.body,
                        'model': 'discuss.channel',
                        'res_id': old_conversation.id,
                        'message_type': msg.message_type,
                        'subject': msg.subject,
                        'parent_id': msg.parent_id.id,
                        'subtype_id': msg.subtype_id.id,
                        'partner_ids': msg.partner_ids.ids,
                    }
                    old_conversation._notify_thread(msg, msg_vals=msg_vals)
            else:
                conversation_data = self._prepare_social_conversation_facebook_data(conversation)
                if conversation_data:
                    conversation_create_datas.append(conversation_data)
        if conversation_create_datas:
            channels = MailChannel.with_user(SUPERUSER_ID).create(conversation_create_datas)
            social_channels_to_update_imange |= channels
            channels_re_show |= channels

        channels_re_show.channel_member_ids.write({'is_pinned': True})
        self._update_chanel_image(social_channels_to_update_imange)

    def _update_chanel_image(self, chanels):
        for chanel in chanels:
            url = host + "/%s?fields=name,profile_pic&access_token=%s" % (
                chanel.social_participant_id,
                self.facebook_page_access_token
            )
            res = requests.get(url)
            self.raise_http_error(res, url)
            data_dict_json = res.json()
            profile_pic_url = data_dict_json.get('profile_pic', False)
            if profile_pic_url:
                image = self._read_image_from_url(profile_pic_url)
                chanel.image_128 = image

    @api.model
    def _check_author_post(self, post, social_page_id):
        author_id = post.get('from', {}).get('id', False)
        return author_id == social_page_id

    def _sync_next_post_facebook(self):
        self.ensure_one()
        self.with_context(inactive_post=False)._synchronized_posts_facebook(self.next_post_sync_url, 5)
        self.notify(_('Post sync successful!'))

    def action_sync_next_posts(self):
        self_todo = self.filtered(lambda r: r.social_provider == 'facebook' and r.next_post_sync_url)
        for r in self_todo:
            r._sync_next_post_facebook()
        return super(SocialPage, self - self_todo).action_sync_next_posts()

    def _cron_sync_all_post(self):
        facebook_pages = self.env['social.page'].search([('social_provider', '=', 'facebook'),
                                                         ('sync_all_post', '=', True),
                                                         ('next_post_sync_url', '!=', False)])
        for page in facebook_pages:
            page._sync_next_post_facebook()

        return super(SocialPage, self)._cron_sync_all_post()

from urllib.parse import urlencode
import requests
import datetime

from odoo import models, fields, _
from dateutil.parser import parse
from odoo.exceptions import UserError

HOST = "https://graph.facebook.com"


class SocialPost(models.Model):
    _inherit = 'social.post'

    schedule_later = fields.Boolean(related='article_id.schedule_later')
    schedule_date = fields.Datetime(string='Schedule Date', related='article_id.schedule_date')

    def _update_facebook_post_list(self, post_list, page_id):
        """
            :param post_list (dict): a dict data is taken from facebook
            :param page_id ('social.page'):
        """
        social_posts = self.env['social.post'].with_context(active_test=False).search([('page_id', '=', page_id)])
        social_post_ids = social_posts.mapped('social_post_id')

        post_ids_new = []
        post_ids_create = []
        post_ids_update = []

        for post in post_list:
            post_ids_new.append(post['id'])
            data = self._prepare_facebook_post_data(post)
            if post['id'] not in social_post_ids:
                data['page_id'] = self._context.get('page_id', False)
                post_ids_create.append(data)
            else:
                data['active'] = True
                post_ids_update.append(data)

        # Post list for Create
        if post_ids_create:
            self.env['social.post'].create(post_ids_create)

        # Post list for Update
        for post in post_ids_update:
            post_update = social_posts.filtered(lambda r: r.social_post_id == post['social_post_id'])
            if post_update:
                post_update.with_context(check_right=False, fields_noupdate=True).write(post)

        # Post list for inactive
        if self._context.get('inactive_post', True):
            posts_for_inactive = social_posts.filtered(lambda r: r.social_post_id not in post_ids_new)
            if posts_for_inactive:
                posts_for_inactive.with_context(check_right=False).write({'active': False})

    def _get_facebook_post_insights(self, post_id, page_access_token):
        """
        TODO: don't use `insights.metric` to get impressions because `read_insights` permission is difficult to get approved.
        More features need to be improved to match what this permission offers.
        """
        url = HOST + "/%s?fields=message,likes.summary(1),shares,comments.filter(stream).limit(1000000).summary(1)" \
                    "&access_token=%s" % (post_id, page_access_token)
        # "insights.metric(post_impressions)&access_token=%s" \
        # % (post_id, page_access_token)
        res = requests.get(url)
        self.raise_http_error(res, url)
        data = res.json()

        total_likes = data.get('likes', {}).get('summary', {}).get('total_count', False)
        total_comments = data.get('comments', {}).get('summary', {}).get('total_count', False)
        total_shares = data.get('shares', {}).get('count', False)
        # views_count = data['insights']['data'][0]['values'][0]['value']
        return {
            'total_likes': total_likes,
            'total_comments': total_comments,
            'total_shares': total_shares,
            'message': data.get('message', ''),
            # 'views_count': views_count
        }

    def _prepare_facebook_post_data(self, post):
        date_posted = parse(post['created_time'])
        date_posted = datetime.datetime.combine(date_posted.date(), date_posted.time())
        state = 'scheduled' if post.get('is_schesdule_later', False) else 'posted'

        attachment = post.get('attachments', {}).get('data', False)
        attachment_link = attachment[0].get('url', False) if attachment and attachment[0].get('type', '') == 'share' else False
        attachment_link_title = attachment[0].get('title', False) if attachment and attachment[0].get('type', '') == 'share' else False

        total_likes = post.get('likes', {}).get('summary', {}).get('total_count', 0)
        total_comments = post.get('comments', {}).get('summary', {}).get('total_count', 0)
        total_shares = post.get('shares', {}).get('count', 0)
        # views_count = post.get('views_count', 0)

        photo_links = []
        if attachment:
            # many photos
            if attachment[0].get('subattachments', False):
                for att_data in attachment[0]['subattachments']['data']:
                    photo_links.append(att_data['media']['image']['src'])
            # one photo
            else:
                photo_links.append(attachment[0]['media']['image']['src'])

        attachment_vals = []
        for p in photo_links:
            attachment_vals.append({
                'name': 'post photo',
                'url': p,
                'type': 'url',
                'public': True
            })
        attachment_ids = self.env['ir.attachment'].create(attachment_vals)

        return {
            'social_post_id': post['id'],
            'social_post_url': post.get('permalink_url', False),
            'message': post.get('message', False),
            'likes_count': total_likes,
            'comments_count': total_comments,
            'shares_count': total_shares,
            # 'views_count': views_count,
            'state': state,
            'date_posted': date_posted,
            'attachment_link': attachment_link,
            'attachment_link_title': attachment_link_title,
            'attachment_ids': [(6, 0, attachment_ids.ids)]
        }

    def _post_article(self):
        self.ensure_one()
        if self.media_id.social_provider != 'facebook':
            return super(SocialPost, self)._post_article()

        params = {
            'access_token': self.page_id.facebook_page_access_token,
            'message': self.message,
            'link': self.attachment_link if self.attachment_link else ""
        }
        if self.schedule_later:
            self._check_schedule_date()
            timestamp = self._datetime_to_timestamp(self.schedule_date or self.article_id.schedule_date)
            params.update({'scheduled_publish_time': timestamp, 'published': 'false'})

        url = HOST + "/%s/feed" % self.page_id.social_page_id
        res = requests.post(url, params=params)
        self.raise_http_error(res, url)
        data = res.json()

        if data:
            url = "https://www.facebook.com/%s" % data['id']
            update_post = self._prepare_data_after_post(data['id'], url)
            if self.schedule_later:
                update_post['state'] = 'scheduled'
                update_post['date_posted'] = self.schedule_date
            self.write(update_post)

    def _check_schedule_date(self):
        self.ensure_one()
        dt_now = datetime.datetime.now()
        dt_scheduled = self.schedule_date or self.article_id.schedule_date
        timedelta = dt_scheduled - dt_now
        seconds = int(timedelta.total_seconds())
        # [30 minutes : 70 days]
        if seconds < 1800 or seconds > 6048000:
            tz = self.env.user.tz
            dt_scheduled = self.env['to.base'].convert_utc_to_local(dt_scheduled, force_local_tz_name=tz)
            dt_scheduled = dt_scheduled.strftime("%x %X")
            raise UserError(
                _("You need to schedule the post within the next 30 minutes to 70 days (%s)") % dt_scheduled)

    def _datetime_to_timestamp(self, date_time):
        return datetime.datetime.timestamp(date_time)

    def _post_file(self):
        self.ensure_one()
        if self.media_id.social_provider != 'facebook':
            return super(SocialPost, self)._post_file()

        url_list = self._get_url_image_list()
        image_ids = self._upload_images_facebook(url_list)
        self._post_article_images_facebook(image_ids)

    def _get_url_image_list(self, attachment_ids=False):
        self.ensure_one()
        if not attachment_ids:
            attachment_ids = self.attachment_ids

        url_list = []
        for attachment in attachment_ids:
            base_url = attachment.get_base_url()
            address_image = '/web/image/%s?access_token=%s' % (attachment.id, attachment.access_token)
            url_list.append(base_url + address_image)
        url_list.reverse()
        return url_list

    def _upload_images_facebook(self, url_list):
        self.ensure_one()
        image_ids = []
        for image_url in url_list:
            url = HOST + "/%s/photos?url=%s&published=false&temporary=true&access_token=%s" \
                  % (self.page_id.social_page_id, image_url, self.page_id.facebook_page_access_token)
            res = requests.post(url)
            self.raise_http_error(res, url)
            data_dict_json = res.json()

            image_id = data_dict_json.get('id', False)
            if image_id:
                image_ids.append(image_id)
        return image_ids

    def _post_article_images_facebook(self, image_ids):
        self.ensure_one()
        if not image_ids:
            return

        param_list = []
        for index, image in enumerate(image_ids):
            param_list.append('attached_media[%s]={"media_fbid":"%s"}' % (index, image))
        if self.schedule_later:
            self._check_schedule_date()
            timestamp = self._datetime_to_timestamp(self.schedule_date)
            param_list.extend(['scheduled_publish_time=%s' % timestamp, 'published=false'])

        str_attachments = '&'.join(param_list)

        url = HOST + "/%s/feed?access_token=%s&%s&" \
                      % (self.page_id.social_page_id,
                         self.page_id.facebook_page_access_token,
                         str_attachments) + urlencode({'message': self.message})
        res = requests.post(url)
        self.raise_http_error(res, url)
        data = res.json()

        if data:
            url = "https://www.facebook.com/%s" % data['id']
            update_post = self._prepare_data_after_post(data['id'], url)
            if self.schedule_later:
                update_post['state'] = 'scheduled'
                update_post['date_posted'] = self.schedule_date
            self.write(update_post)

    def _delete_post_social(self):
        self.ensure_one()
        if self.media_id.social_provider != 'facebook':
            return super(SocialPost, self)._delete_post_social()

        url = HOST + "/%s?access_token=%s" % (self.social_post_id, self.page_id.facebook_page_access_token)
        res = requests.delete(url)
        self.raise_http_error(res, url)

    def _get_post_comments_facebook(self, post_or_comment_id, comment_type):
        self.ensure_one()
        page_access_token = self.page_id.facebook_page_access_token
        order_by = 'reverse_chronological' if comment_type == 'comment' else 'chronological'

        if not post_or_comment_id or not page_access_token:
            raise Exception("'post_or_comment_id' or page_access_token has no value.")

        url = HOST + "/%s/comments?fields=attachment,comment_count,like_count,user_likes,from{id,name,picture}" \
                     ",created_time,message,is_hidden&order=%s&limit=20&access_token=%s" \
                     % (post_or_comment_id, order_by, page_access_token)
        res = requests.get(url)
        self.raise_http_error(res, url)
        data = res.json().get('data', False)

        page_id = self.page_id.social_page_id

        for comment in data:
            author = comment.get('from', False)
            if author:
                author.update({'author_image': author.get('picture', {}).get('data', {}).get('url', False)})
            else:
                comment['from'] = {
                    'id': False,
                    'name': '# User',
                    'author_image_src': '/viin_social_facebook/static/img/user_default.png'
                }
            date_comment = parse(comment['created_time'])
            date_comment = datetime.datetime.combine(date_comment.date(), date_comment.time())
            date_comment = self._set_datetime(date_comment)
            comment.update({'created_time': date_comment})

            comment.update({
                'page_id': page_id,
                'is_page_comment': comment.get('from', {}).get('id') == page_id
            })

            attachment = comment.get('attachment', False)
            if attachment:
                attachment_type = attachment.get('type', False)
                if attachment_type == 'animated_image_share':
                    attachment_source = attachment.get('media', {}).get('source', False)
                else:
                    attachment_source = attachment.get('media', {}).get('image', {}).get('src', False)
                comment.update({
                    'attachment': {
                        'type': attachment_type,
                        'src': attachment_source
                    }
                })
        return data

    def _add_comment_facebook(self, comment_message, comment_id=False):
        self.ensure_one()
        self._check_right_comment()
        comment_or_post_id = comment_id or self.social_post_id
        page_access_token = self.page_id.facebook_page_access_token

        if not (comment_or_post_id and comment_message and page_access_token):
            raise Exception("'comment_or_post_id' or 'comment_message' or 'page_access_token' has no value.")

        url = HOST + "/%s/comments?access_token=%s" % (comment_or_post_id, page_access_token)
        res = requests.post(url, data={'message': comment_message})
        self.raise_http_error(res, url)
        return res.json().get('id', False)

    def _check_like_comment_facebook(self, comment_id, page_access_token):
        self.ensure_one()
        if comment_id and page_access_token:
            url = HOST + "/%s?fields=user_likes&access_token=%s" % (comment_id, page_access_token)
            res = requests.get(url)
            self.raise_http_error(res, url)
            data = res.json()
            if data.get('user_likes', False):
                return True
        return False

    def _like_comment_facebook(self, comment_id):
        self.ensure_one()
        self._check_right_comment()
        page_access_token = self.page_id.facebook_page_access_token

        if not comment_id or not page_access_token:
            raise Exception("'comment_id' or 'page_access_token' has no value.")

        user_liked = self._check_like_comment_facebook(comment_id, page_access_token)
        if user_liked:
            return False

        url = HOST + "/%s/likes?access_token=%s" % (comment_id, page_access_token)
        res = requests.post(url)
        self.raise_http_error(res, url)
        return res.json().get('success', False)

    def _unlike_comment_facebook(self, comment_id):
        self.ensure_one()
        self._check_right_comment()
        page_access_token = self.page_id.facebook_page_access_token

        if not comment_id or not page_access_token:
            raise Exception("'comment_id' or 'page_access_token' has no value.")

        url = HOST + "/%s/likes?access_token=%s" % (comment_id, page_access_token)
        res = requests.delete(url)
        self.raise_http_error(res, url)
        return res.json().get('success', False)

    def _delete_comment_facebook(self, comment_id):
        self.ensure_one()
        self._check_right_comment()
        page_access_token = self.page_id.facebook_page_access_token

        if not comment_id or not page_access_token:
            raise Exception("'comment_id' or 'page_access_token' has no value.")

        url = HOST + "/%s?access_token=%s" % (comment_id, page_access_token)
        res = requests.delete(url)
        self.raise_http_error(res, url)
        return res.json().get('success', False)

    def _hide_comment_facebook(self, comment_id):
        return self._toggle_hide_comment_facebook(comment_id, True)

    def _unhide_comment_facebook(self, comment_id):
        return self._toggle_hide_comment_facebook(comment_id, False)

    def _toggle_hide_comment_facebook(self, comment_id, is_hidden):
        self.ensure_one()
        self._check_right_comment()
        page_access_token = self.page_id.facebook_page_access_token

        if not comment_id or not page_access_token:
            raise Exception("'comment_id' or 'page_access_token' has no value.")

        url = HOST + "/%s?is_hidden=%s&access_token=%s" % (comment_id, is_hidden, page_access_token)
        res = requests.post(url)
        data = res.json()
        try:
            self.raise_http_error(res, url)
        except requests.HTTPError:
            return {'msg_error': data.get('error', {}).get('message', 'Can not hide or unhide this comment')}
        return data

    def _update_post_engagement_facebook(self):
        self.ensure_one()
        post_id = self.social_post_id
        page_access_token = self.page_id.facebook_page_access_token
        engagement = self._get_facebook_post_insights(post_id, page_access_token)

        if engagement:
            likes_count = engagement.get('total_likes', False) or self.likes_count
            comments_count = engagement.get('total_comments', False) or self.comments_count
            shares_count = engagement.get('total_shares', False) or self.shares_count
            self.write({
                'likes_count': likes_count,
                'comments_count': comments_count,
                'shares_count': shares_count,
                'message': engagement['message'],
                # 'views_count': engagement['views_count']
            })
        # return to update view in javascript
        return {
            'comments_count': self.comments_count,
            'likes_count': self.likes_count,
            'shares_count': self.shares_count,
            'message': engagement['message'],
        }

    def _get_post_attachment_facebook(self):
        self.ensure_one()
        attachments = []
        page_access_token = self.page_id.facebook_page_access_token
        post_id = self.social_post_id

        if not post_id or not page_access_token:
            raise Exception("'post_id' or 'page_access_token' has no value.")

        url = HOST + "/%s/attachments?access_token=%s" % (post_id, page_access_token)
        res = requests.get(url)
        self.raise_http_error(res, url)
        data = res.json()

        for element in data.get('data', False):
            if element.get('subattachments', False):
                for attachment in element.get('subattachments', {}).get('data', False):
                    attachment_type = attachment.get('type', False)
                    if attachment_type == 'animated_image_share':
                        attachment_source = attachment.get('media', {}).get('source', False)
                    else:
                        attachment_source = attachment.get('media', {}).get('image', {}).get('src', False)
                    if attachment_source:
                        attachments.append({'type': attachment_type, 'src': attachment_source})
            elif element.get('media', {}).get('image', {}).get('src', False):
                attachments.append({
                    'type': 'photo',
                    'src': element['media']['image']['src']
                })

        return attachments

    def update_social_post(self):
        self.ensure_one()
        if self.media_id.social_provider != 'facebook' or self.state not in ('posted', 'scheduled'):
            return super(SocialPost, self).update_social_post()
        if self.schedule_later and self.state != 'scheduled':
            raise UserError(_("You only set a scheduled publish time on an unpublished post"))
        if not self.schedule_later and self.state == 'scheduled':
            raise UserError(_("You cannot post immediately by unchecking the Schedule later field"))

        fb_attached_media = []
        if self.attachment_ids != self.article_id.attachment_ids:
            self.attachment_ids = self.article_id.attachment_ids
            attachments_url = self._get_url_image_list(attachment_ids=self.article_id.attachment_ids)
            fb_image_ids = self._upload_images_facebook(attachments_url)
            for img_id in fb_image_ids:
                fb_attached_media.append({'media_fbid': img_id})

        url = "https://graph.facebook.com/%s?access_token=%s" % (self.social_post_id, self.page_id.facebook_page_access_token)
        params = {
            'message': self.message
        }
        params.update({'attached_media': str(fb_attached_media)})

        if self.schedule_later:
            self._check_schedule_date()
            timestamp = self._datetime_to_timestamp(self.schedule_date)
            params.update({'scheduled_publish_time': int(timestamp)})

        res = requests.post(url, data=params)
        self.raise_http_error(res, url)

        return super(SocialPost, self).update_social_post()

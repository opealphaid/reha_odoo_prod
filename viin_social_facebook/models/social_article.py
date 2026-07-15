import base64
from datetime import datetime

import requests
from lxml import html

from odoo import fields, models, api, _
from odoo.exceptions import UserError


host = "https://graph.facebook.com/v24.0"


class SocialArticle(models.Model):
    _inherit = 'social.article'

    display_facebook_preview = fields.Boolean('Display Facebook Preview', compute='_compute_display_facebook_preview')
    facebook_preview = fields.Html('Facebook Preview', compute='_compute_facebook_preview')

    @api.constrains('schedule_date')
    def _check_schedule_date(self):
        for r in self:
            if r.schedule_later and r.schedule_date:
                dt_now = datetime.now()
                dt_scheduled = r.schedule_date
                timedelta = dt_scheduled - dt_now
                seconds = int(timedelta.total_seconds())

                if seconds < 1800 or seconds > 6048000:
                    for page in r.page_ids:
                        if page.social_provider == 'facebook':
                            raise UserError(_("You need to schedule the post within the next 30 minutes to 70 days"))

    @api.depends('message', 'page_ids.media_id.social_provider')
    def _compute_display_facebook_preview(self):
        for r in self:
            r.display_facebook_preview = r.message and ('facebook' in r.page_ids.media_id.mapped('social_provider'))

    @api.depends('message', 'attachment_ids', 'attachment_link', 'attachment_type', 'display_facebook_preview')
    def _compute_facebook_preview(self):
        convert_utc_to_local = self.env['to.base'].convert_utc_to_local
        for r in self:
            if r.display_facebook_preview:
                dt_now = r.schedule_date if r.schedule_later else fields.Datetime.now()
                dt_now = convert_utc_to_local(dt_now, self.env.user.tz, naive=True)
                data_dict = {
                    'message': r.message,
                    'published_date': dt_now
                }
                if r.attachment_type == 'none' and r.attachment_link:
                    req = requests.get(r.attachment_link)
                    req.raise_for_status()
                    data = html.fromstring(req.text.encode('utf-8'), parser=html.HTMLParser(encoding='utf-8'))
                    if data:
                        data_dict.update({
                            'title': data.xpath("//meta[@property='og:title']")[0].attrib.get('content', False) if data.xpath("//meta[@property='og:title']") else r.attachment_link_title,
                            'description': data.xpath("//meta[@property='og:description']")[0].attrib.get('content', '') if data.xpath("//meta[@property='og:description']") else '',
                            'site_name': r.attachment_link.split("//")[1].split("/")[0],
                            'image_url': data.xpath("//meta[@property='og:image']")[0].attrib.get('content', False) if data.xpath("//meta[@property='og:image']") else False
                        })
                elif r.attachment_type == 'file' and r.attachment_ids:
                    attachments = r.attachment_ids.sorted('id') if r.attachment_ids == r.attachment_ids._origin else r.attachment_ids
                    attachments_preview = self._get_attachments_preview(attachments)
                    data_dict.update({
                        'images': attachments_preview
                    })
                r.facebook_preview = self.env['ir.ui.view']._render_template('viin_social_facebook.facebook_preview', data_dict)
            else: r.facebook_preview = False

    def _get_attachments_preview(self, attachments):
        try:
            attachments_preview = [image.datas if not image.id else base64.b64encode(open(image._full_path(image.store_fname), 'rb').read()) for image in attachments]
            return attachments_preview
        except Exception:
            raise UserError(_("File is not supported."))

    def _check_attachments(self, attachments):
        for file in attachments:
            if file.mimetype in ('image/png', 'image/jpeg'):
                if file.file_size > 4000000:
                    raise UserError(_("Facebook Page: You cannot post image > 4Mb"))
            else:
                raise UserError(_("Facebook Page: Please select a supported image format (<4Mb): *png, *jpeg. Video is not supported at this time"))

    def _action_confirm(self):
        self.ensure_one()
        if self.attachment_type == 'file' and 'facebook' in self.media_ids.mapped('social_provider'):
            self._check_attachments(self.attachment_ids)
        return super(SocialArticle, self)._action_confirm()

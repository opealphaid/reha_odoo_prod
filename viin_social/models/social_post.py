from markupsafe import Markup
from odoo import models, fields, api, SUPERUSER_ID, _
from odoo.tools.image import image_data_uri
from odoo.exceptions import UserError


class SocialPost(models.Model):
    _name = 'social.post'
    _inherit = ['social.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Social Post'
    _order = 'date_posted desc'

    name = fields.Char(string='Title', compute='_compute_name')
    article_id = fields.Many2one('social.article', string='Article', help="Source of this post", readonly=True)
    page_id = fields.Many2one('social.page', string='Page', required=True, readonly=True, ondelete='cascade')
    message = fields.Text(string='Content', help="Content of this post", readonly=True)
    message_view_more = fields.Text(string='Message More', help="Showing 1 piece of content in addition to the kanban",
                                    compute="_compute_message_view_more")
    attachment_type = fields.Selection(related='article_id.attachment_type', store=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Attach Images/Videos')
    attachment_link = fields.Char(string='Attach Link', readonly=True)
    attachment_link_title = fields.Char(string='Attach Link Title', readonly=True)
    media_id = fields.Many2one('social.media', related='page_id.media_id', store=True)
    likes_count = fields.Integer(string='Total Likes', readonly=True)
    comments_count = fields.Integer(string='Total Comments', readonly=True)
    shares_count = fields.Integer(string='Total Shares', readonly=True)
    views_count = fields.Integer(string='Total Views', readonly=True)
    social_post_id = fields.Char(string='Social Post ID', help="ID of this post on Social Media", readonly=True)
    social_post_url = fields.Char(string='Social Post URL', help="URL of this post on Social Media", readonly=True)
    state = fields.Selection([('ready', 'Ready'),
                              ('scheduled', 'Scheduled'),
                              ('posted', 'Posted'),
                              ('cancelled', 'Cancelled')], string='State', default='ready', readonly=True, tracking=True)
    active = fields.Boolean(string="Active", default=True)
    date_posted = fields.Datetime(string="Date Posted", readonly=True)
    user_posted = fields.Many2one('res.users', string='Posted by', readonly=True)
    post_on_my_page = fields.Boolean(compute="_compute_post_on_my_page", search='_search_post_on_my_page')
    company_id = fields.Many2one('res.company', string='Company', related='page_id.company_id', store=True)

    _sql_constraints = [
        ('unique_social_post_id',
         'UNIQUE(social_post_id, company_id)',
         "Social Post must be unique to each company!"),
    ]

    @api.depends('page_id.member_ids')
    def _compute_post_on_my_page(self):
        for r in self:
            if r.env.user in r.page_id.member_ids:
                r.post_on_my_page = True
            else:
                r.post_on_my_page = False

    def _search_post_on_my_page(self, operator, operand):
        if operator not in ['=', '!='] or not isinstance(operand, bool):
            raise UserError(_('Operation not supported'))
        if operator == '=':
            return [('page_id.member_ids', 'in', self.env.user.ids)]
        return [('page_id.member_ids', 'not in', self.env.user.ids)]

    @api.depends('message')
    def _compute_name(self):
        for r in self:
            name = ''
            if isinstance(r.message, str):
                name = r.message[:40]
                if len(r.message) > 40:
                    name += '...'
            r.name = name

    @api.depends('message')
    def _compute_message_view_more(self):
        for r in self:
            if r.message and len(r.message) > 140:
                r.message_view_more = r.message[0:140]
            else:
                r.message_view_more = False

    def _update_attachment(self):
        for r in self:
            r.attachment_ids.write({'res_id': r.id, 'res_model': 'social.post'})

    @api.model_create_multi
    def create(self, vals_list):
        res = super(SocialPost, self).create(vals_list)
        res._update_attachment()
        return res

    def write(self, vals):
        if self._context.get('check_right', True):
            self._check_access_on_post()
        if vals.get('state', False):
            origin_state = dict(self._fields['state'].selection).get(self.state, False)
            new_state = dict(self._fields['state'].selection).get(vals['state'], False)
            for r in self:
                if r.article_id:
                    body = _("<ul class='o_mail_thread_message_tracking'> \
                                <li>%(page_name)s Post State: %(origin_state)s \
                                    <span class='fa fa-long-arrow-right' role='img' aria-label='Changed' title='Changed'></span> %(new_state)s \
                                </li> \
                            </ul>") % {
                                'page_name': r.page_id.display_name,
                                'origin_state': origin_state,
                                'new_state': new_state,
                            }
                    r.article_id.message_post(body=Markup(body))
        res = super(SocialPost, self).write(vals)
        self._update_attachment()
        return res

    def unlink(self):
        if self._context.get('check_right', True):
            self._check_access_on_post()
        for article in self.article_id:
            posts_remove = self.filtered(lambda record: record.article_id == article)
            body = _("<ul class='o_mail_thread_message_tracking'> \
                        <li>%(post_count)s Post is removed: %(page_names)s</li> \
                    </ul>") % {
                        'post_count': len(posts_remove),
                        'page_names': ", ".join(posts_remove.mapped('page_id.display_name')),
                    }
            article.message_post(body=Markup(body))
        return super(SocialPost, self).unlink()

    def action_post_article(self):
        self.ensure_one()
        user = self.env.user
        if user.has_group('viin_social.viin_social_group_admin') or user.has_group('viin_social.viin_social_group_approve'):
            self = self.with_context(check_right=False)
            if self.attachment_type == 'file':
                self._post_file()
            else:
                self._post_article()
            partner_ids = (self.article_id.author_id + self.article_id.assign_id - self.env.user).partner_id.ids
            self.article_id.with_user(SUPERUSER_ID).message_post(
                body=_("Article: %s was posted on social media") % self.article_id.name,
                partner_ids=partner_ids
            )
        else:
            raise UserError(_("You don't have rights post article to the page"))

    def action_cancel_post(self):
        self.write({'state': 'cancelled'})

    def action_set_ready_post(self):
        self.write({'state': 'ready'})

    def action_delete_post(self):
        if self._context.get('check_right', True):
            self._check_access_on_post()
        posted = self.filtered(lambda r: r.state in ('posted', 'scheduled'))
        for r in posted:
            r._delete_post_social()
        self.unlink()

    def action_view_post(self):
        self.ensure_one()
        if self.social_post_url:
            return {
                'type': 'ir.actions.act_url',
                'url': self.social_post_url,
                'target': 'new'
            }

    def action_edit_post(self):
        self._check_access_on_post()
        ctx = {
            'default_post_id': self.id,
            'default_message': self.message
        }
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'social.post.action.edit.post',
            'view_mode': 'form',
            'view_id': self.env.ref('viin_social.social_post_action_edit_post_view_form').id,
            'target': 'new',
            'context': ctx,
        }

    @api.model
    def action_synchronize_all_post(self):
        pages = self.env['social.page'].search([])
        for page in pages:
            page.sudo().action_sinchronized_posts()

    def _post_article(self):
        # for inherit
        pass

    def _post_file(self):
        # for inherit
        pass

    def _delete_post_social(self):
        # for inherit
        pass

    def action_delete_post_in_social(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Confirm Delete Post In Social'),
            'res_model': 'wizard.social.confirm',
            'view_mode': 'form',
            'view_id': self.env.ref('viin_social.wizard_social_confirm_view_form').id,
            'target': 'new',
            'context': {
                'message': "Are you sure you want to delete these posts (include social pages)?",
                'res_ids': self.ids,
                'model': 'social.post',
                'method': 'action_delete_post'
            }
        }

    def _prepare_data_after_post(self, social_post_id, post_url):
        return {
            'social_post_id': social_post_id,
            'social_post_url': post_url,
            'date_posted': fields.Datetime.now(),
            'user_posted': self.env.user.id,
            'state': 'posted'
        }

    def _check_access_on_post(self):
        user = self.env.user
        for r in self:
            check_access = user in r.page_id.assign_id + r.media_id.assign_id
            check_raise = False
            if not user.has_group('viin_social.viin_social_group_admin') and not check_access:
                check_raise = True
            if r.state in ('posted', 'scheduled'):
                if not user.has_group('viin_social.viin_social_group_approve'):
                    check_raise = True
            if check_raise:
                raise UserError(_("You don't have rights on the post: %s") % r)

    def _get_post_comments(self, comment_or_post_id, comment_type):
        result = self._call_dynamic_method('_get_post_comments_', comment_or_post_id, comment_type)
        return result if result else []

    def get_post_content(self):
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_("The post has not been posted."))

        comments = []
        if self.state == 'posted':
            social_post_id = self.social_post_id
            comment_type = 'comment'
            comments = self._get_post_comments(social_post_id, comment_type)

        attachments = []
        for attachment in self.attachment_ids:
            base_url = attachment.get_base_url()
            address_image = '/web/image/%s' % attachment.id
            attachments.append({
                'type': 'photo',
                'src': base_url + address_image
            })

        if not self.attachment_ids:
            attachments = self._get_post_attachment()
        post_data = {
            'post_id': self.id,
            'page_name': self.page_id.name,
            'page_image': image_data_uri(self.page_id.image) if self.page_id.image else False,
            'post_message': self.message,
            'post_like_count': self.likes_count,
            'post_comment_count': self.comments_count,
            'first_level_comment_count': len(comments),
            'post_share_count': self.shares_count,
            'social_media_name': self.media_id.name,
            'attachments': attachments,
            'attachment_link': self.attachment_link,
            'attachment_link_title': self.attachment_link_title,
            'media': self.media_id,
            'comments': comments,
            'state': self.state,
            'social_page_id': self.page_id.social_page_id,
        }
        return post_data

    def get_reply_comments(self, comment_id):
        comment_type = 'reply'
        reply_data = {'replys': self._get_post_comments(comment_id, comment_type)}
        return reply_data

    def _add_comment(self, comment_message, comment_id=False):
        return self._call_dynamic_method('_add_comment_', comment_message, comment_id)

    def add_comment(self, comment_message, comment_id=False):
        self.ensure_one()
        self._check_posted()
        return_comment_id = self._add_comment(comment_message, comment_id)
        comment_data = False
        if return_comment_id:
            data = {
                'id': return_comment_id,
                'comment_count': 0,
                'like_count': 0,
                'message': comment_message,
                'created_time': self._set_datetime(fields.Datetime.now()),
                'is_page_comment': True,
                'from': {
                    'name': self.page_id.name,
                    'page_image': self.page_id.image and image_data_uri(self.page_id.image) or False
                }
            }
            if comment_id:
                comment_data = {
                    'replys': [data]
                }
            else:
                comment_data = {
                    'page_image': self.page_id.image and image_data_uri(self.page_id.image) or False,
                    'comments': [data]
                }
        return comment_data

    def _like_comment(self, comment_id, unlike=False):
        if unlike:
            return self._call_dynamic_method('_unlike_comment_', comment_id)
        else:
            return self._call_dynamic_method('_like_comment_', comment_id)

    def like_comment(self, comment_id):
        self.ensure_one()
        if self._like_comment(comment_id):
            return 1
        elif self._like_comment(comment_id, unlike=True):
            return -1
        else:
            return 0

    def _delete_comment(self, comment_id):
        if not self.env.user.has_group('viin_social.viin_social_group_approve') and \
               not self.env.user.has_group('viin_social.viin_social_group_admin'):
            raise UserError(_("You don't have permission to delete comments."))

        self._check_right_comment()
        return self._call_dynamic_method('_delete_comment_', comment_id)

    def _hide_comment(self, comment_id):
        self._check_right_comment()
        return self._call_dynamic_method('_hide_comment_', comment_id)

    def _unhide_comment(self, comment_id):
        self._check_right_comment()
        return self._call_dynamic_method('_unhide_comment_', comment_id)

    def delete_comment(self, comment_id):
        return self._delete_comment(comment_id)

    def hide_comment(self, comment_id):
        return self._hide_comment(comment_id)

    def unhide_comment(self, comment_id):
        return self._unhide_comment(comment_id)

    def _update_post_engagement(self):
        self.ensure_one()
        if self.media_id.social_provider != 'none':
            custom_update_post_engagement_method = '_update_post_engagement_%s' % self.media_id.social_provider
            if hasattr(self, custom_update_post_engagement_method):
                data = getattr(self.with_context(check_right=False), custom_update_post_engagement_method)()
                return data

    def _check_posted(self):
        for r in self:
            if r.state != 'posted':
                raise UserError(_("The post has not been posted."))

    def update_post_engagement(self):
        self.ensure_one()
        for r in self:
            if r.state != 'posted':
                return
        return self._update_post_engagement()

    def _update_post_from_notice(self, social_post_id):
        post = self.env['social.post'].sudo().search([('social_post_id', '=', social_post_id)], limit=1)
        if post:
            post._update_post_engagement()

    def _get_post_attachment(self):
        result = self._call_dynamic_method('_get_post_attachment_')
        return result if result else []

    def _check_right_comment(self):
        self.ensure_one()
        admins = self.env.ref("viin_social.viin_social_group_admin").with_context(active_test=True).users
        users = self.page_id.member_ids + self.page_id.assign_id + self.page_id.media_id.assign_id + admins
        if self.env.user not in users:
            raise UserError(_("you don't have permission on the post"))

    def _set_datetime(self, datetime):
        user_tz = self.env.user.tz
        return self.env['to.base'].convert_utc_to_local(datetime, force_local_tz_name=user_tz)

    def _cron_announce_the_scheduled_post_has_been_posted(self):
        scheduled_post = self.search([('state', '=', 'scheduled')])
        for r in scheduled_post:
            if r.article_id.schedule_date and fields.Datetime().now() >= r.article_id.schedule_date:
                r.with_user(SUPERUSER_ID).state = 'posted'
                receivers = (
                    r.article_id.author_id
                    + r.article_id.assign_id
                    + r.page_id.member_ids
                ).partner_id
                body = _('This scheduled post may have already been posted on the page: <b>%s</b>') % r.page_id.name
                r.with_user(SUPERUSER_ID).message_post(body=Markup(body), partner_ids=receivers.ids)

    def _call_dynamic_method(self, func_first_name, *args, **kwargs):
        result = False
        if self.media_id.social_provider != 'none':
            custom_method = func_first_name + '%s' % self.media_id.social_provider
            if hasattr(self, custom_method):
                result = getattr(self, custom_method)(*args, **kwargs)
        return result

    def update_social_post(self):
        pass

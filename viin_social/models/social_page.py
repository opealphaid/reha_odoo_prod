import requests
import base64
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SocialPage(models.Model):
    _name = 'social.page'
    _inherit = ['social.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Social Page'
    _mail_post_access = 'read'

    name = fields.Char(string='Name', required=True, readonly=True, help="Name of this page on Social Media")
    description = fields.Text(string='Description', readonly=True, help="Description of this page on Social Media")
    media_id = fields.Many2one('social.media', string='Social Media', ondelete='cascade', help="The Social Media which this page belongs", readonly=True)
    social_provider = fields.Char(readonly=True, help="Use to hide fields of other social")
    image = fields.Binary(string='Avatar', help="Avatar of this page", attachment=False)
    post_ids = fields.One2many('social.post', 'page_id', string='Posts', help="Posts on this page")
    article_ids = fields.Many2many('social.article', string='Articles', help="Sources of the posts on this page")
    social_page_id = fields.Char(string="Page Id on Social", readonly=True)
    social_page_url = fields.Char(string="URL of Social", readonly=True)
    assign_id = fields.Many2one('res.users', string='Approver', domain="[('id', 'in', users_can_select_ids)]",
                                help="User has rights to all posts of this page on social networks")
    users_can_select_ids = fields.Many2many('res.users', compute='_compute_users_can_select_ids')
    active = fields.Boolean(string="Active", readonly=True, default=True)
    follower_count = fields.Integer(string='Total followers', readonly=True)
    engagement_count = fields.Integer(string='Total Engagements', readonly=True)
    view_count = fields.Integer(string='Total Views', readonly=True)
    like_count = fields.Integer(string='Total Likes', readonly=True)
    comment_count = fields.Integer(string='Total Comments', readonly=True)
    share_count = fields.Integer(string='Total Shares', readonly=True)
    click_count = fields.Integer(string='Total Clicks', readonly=True)
    member_ids = fields.Many2many('res.users', string='Members', domain="[('id', 'in', users_can_select_ids)]",
                                  compute='_compute_member_ids', store=True, readonly=False,
                                  help="All members can: Receive Notifications, Reply/Delete Comments, "
                                  "and are default members on social conversation.")
    source_id = fields.Many2one('utm.source', string='Source')
    company_id = fields.Many2one('res.company', string='Company', related='media_id.company_id', store=True)

    _sql_constraints = [
        ('unique_social_social_page_id_social_page_url',
         'UNIQUE(social_page_id, social_page_url, company_id)',
         "You cannot have two pages with the same Social Page and Social Network URL of the same company!"),
    ]

    @api.depends('assign_id', 'media_id.assign_id', 'media_id.company_id')
    def _compute_member_ids(self):
        for r in self:
            users_admin = self.env['res.users'].search(
            [('groups_id.id', '=', self.env.ref('viin_social.viin_social_group_admin').id), ('company_ids', 'in', r.company_id.id)])
            members = r.member_ids + users_admin
            if r.assign_id not in members:
                members += r.assign_id
            if r.media_id.assign_id not in members:
                members += r.media_id.assign_id
            r.member_ids = members

    @api.depends('name')
    def _compute_display_name(self):
        for r in self:
            r.display_name = "[%s] %s" % (r.media_id.name, r.name)

    def _compute_users_can_select_ids(self):
        group_approve = self.env.ref('viin_social.viin_social_group_editor', raise_if_not_found=False)
        for r in self:
            user = group_approve.users.filtered(lambda u: u.company_id == r.company_id)
            r.users_can_select_ids = user

    def write(self, vals):
        user = self.env.user
        if not user.has_group('viin_social.viin_social_group_admin'):
            for r in self:
                if 'member_ids' in vals.keys():
                    if user not in r.assign_id + r.media_id.assign_id:
                        raise UserError(_("Only the assigned user or Manager can edit members"))
        if 'active' in vals:
            if not vals['active']:
                self.env['social.post'].search([('page_id', 'in', self.ids)]).write({'active': False})

                self.env['discuss.channel'].with_context(active_test=False).search([
                    ('channel_type', '=', 'social_chat'),
                    ('social_page_id.social_page_id', 'in', self.mapped('social_page_id'))
                ]).channel_member_ids.write({
                    'is_pinned': False
                })

        return super(SocialPage, self).write(vals)

    def action_sinchronized_posts(self):
        return self.notify(_('Post sync successful!'))

    def action_sinchronized_page(self):
        """ Synchronize basic information of current page """
        self.ensure_one()
        return self.notify(_("Synchronize information of the page: %s successful") % self.name)

    def _read_image_from_url(self, url, timeout=5):
        if not url:
            return False
        try:
            resp = requests.get(url.strip(), timeout=timeout)
            resp.raise_for_status()
            content_type = resp.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/'):
                return False

            return base64.b64encode(resp.content)

        except Exception as e:
            _logger.error(f"Error reading image from URL: {url}, error: {e}")
            return False

    def action_get_social_page_message(self):
        self._get_social_page_message()

    def _get_social_page_message(self):
        user = self.env.user
        for r in self:
            users = r.assign_id + r.media_id.assign_id
            if self._context.get('check_group', True):
                if not user.has_group('viin_social.viin_social_group_admin') and user not in users:
                    raise UserError(_("Only the assigned user on Page/Media or Manager can synch message"))

            if r.media_id.social_provider != 'none':
                custom_get_social_page_message_method = '_get_social_page_message_%s' % r.media_id.social_provider
                if hasattr(self, custom_get_social_page_message_method):
                    getattr(r, custom_get_social_page_message_method)()

    def action_sync_next_posts(self):
        pass

    def _cron_sync_all_post(self):
        pass

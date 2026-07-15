import requests
from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SocialArticle(models.Model):
    _name = 'social.article'
    _inherit = ['social.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Social Article'
    _order = 'create_date desc'
    _mail_post_access = 'read'

    def _default_domain_user(self):
        if self.env.user.has_group('viin_social.viin_social_group_approve'):
            return []
        return [('id', '=', self.env.user.id)]

    name = fields.Char(string="Title", required=True, tracking=True)
    post_ids = fields.One2many('social.post', 'article_id', string='Posts', help="Posts from this article")
    page_ids = fields.Many2many('social.page', string='Post on', tracking=True)
    message = fields.Text(string='Body', help="Content of this article", required=True, tracking=True)
    message_view_more = fields.Text(string='Message More', help="Showing 1 piece of content in addition to the kanban",
                                    compute="_compute_message_view_more")
    attachment_type = fields.Selection([('none', "None"),
                                        ('file', "Attach Files")], default='none', string="Attachment Type",
                                       help="Files: Image or Videos")
    attachment_ids = fields.Many2many(comodel_name='ir.attachment', relation='social_article_ir_attachment_image_rel',
                                      string='Attach Images/Videos')
    attachment_link = fields.Char(string='Attach Link')
    attachment_link_title = fields.Char(string='Attach Link Title')
    author_id = fields.Many2one('res.users', string='Author', default=lambda self: self.env.user, readonly=True)
    assign_id = fields.Many2one('res.users', string='Assign to', default=lambda self: self.env.user,
                                domain=_default_domain_user, tracking=True,
                                help="User has right to this article")
    state = fields.Selection([('draft', 'Draft'),
                              ('confirmed', 'Confirmed'),
                              ('cancelled', 'Cancelled')], string='State', default='draft', tracking=True)
    post_count = fields.Integer(string="Total posts posted", compute='_compute_post_count')
    media_ids = fields.Many2many('social.media', string='Post on Media', compute='_compute_media_ids')
    can_cancel = fields.Boolean(string='Can Cancel', compute='_compute_can_cancel')
    schedule_later = fields.Boolean(string='Schedule later', default=False, tracking=True)
    schedule_date = fields.Datetime(string='Scheduled Post Date', tracking=True,
                                    help="You need to schedule the post within the next 30 minutes to 70 days, "
                                         "since the post is confirmed by the user with approval permission.")
    active = fields.Boolean(string="active", default=True)
    posts_state = fields.Selection([('not_posted', 'Not Posted'),
                                    ('posted', 'Posted')], string='Posts State', compute='_compute_posts_state', store=True)
    hide_button_post_article = fields.Boolean(string='Hide Button Post Article',
                                              compute='_compute_hide_button_post_article')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, required=True)

    def _compute_hide_button_post_article(self):
        for r in self:
            if r.state != 'confirmed' or r.posts_state == 'posted' or 'scheduled' in r.post_ids.mapped('state'):
                r.hide_button_post_article = True
            else:
                r.hide_button_post_article = False

    @api.depends('post_ids.state')
    def _compute_posts_state(self):
        for r in self:
            if r.post_ids.filtered(lambda p: p.state == 'posted'):
                r.posts_state = 'posted'
            else:
                r.posts_state = 'not_posted'

    def _compute_can_cancel(self):
        for r in self:
            current_user = self.env.user
            if (self.state == 'confirmed'
                    and ((current_user == r.assign_id and current_user.has_group('viin_social.viin_social_group_approve')
                          or current_user.has_group('viin_social.viin_social_group_admin')))):
                r.can_cancel = True
            else:
                r.can_cancel = False

    @api.depends('page_ids')
    def _compute_media_ids(self):
        for r in self:
            r.media_ids = r.page_ids.media_id

    @api.depends('post_ids', 'post_ids.state')
    def _compute_post_count(self):
        data = self.env['social.post']._read_group([('article_id', 'in', self.ids)], ['article_id'], ['__count'])
        articles_data = {article.id: count for article, count in data}
        for r in self:
            r.post_count = articles_data.get(r.id, 0)

    @api.depends('message')
    def _compute_message_view_more(self):
        for r in self:
            if r.message and len(r.message) > 140:
                r.message_view_more = r.message[0:140]
            else:
                r.message_view_more = False

    @api.onchange('attachment_link')
    def _onchange_attachment_link(self):
        self._check_attachment_link()

    def _update_attachment(self):
        for r in self:
            r.attachment_ids.write({'res_id': r.id, 'res_model': 'social.article'})

    @api.model_create_multi
    def create(self, vals_list):
        res = super(SocialArticle, self).create(vals_list)
        res._update_attachment()
        return res

    def write(self, vals):
        if 'attachment_type' in vals and vals['attachment_type'] == 'none':
            for r in self:
                r.attachment_ids = False

        for r in self:
            if r.state == 'confirmed' and not r.post_ids.filtered(lambda post: post.state == 'posted'):
                fields_check = ['name', 'page_ids', 'message', 'attachment_type', 'attachment_ids', 'attachment_link',
                                'attachment_link_title', 'assign_id', 'schedule_later', 'schedule_date']
                for f in fields_check:
                    if f in vals:
                        raise UserError(_("This article has no social media posts yet, you need to set it to draft to be able to edit it."))

        result = super(SocialArticle, self).write(vals)
        self._update_attachment()
        self.attachment_ids.generate_access_token()
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_except_confirmed(self):
        for r in self:
            if r.state == 'confirmed':
                raise UserError(_("You cannot delete Article %s when state is 'Confirmed'") % r.name)

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_confirm(self):
        for r in self:
            r._action_confirm()

    def _action_confirm(self):
        self.ensure_one()
        if not self.page_ids:
            raise UserError(_("You need to choose at least one page"))
        if self.attachment_type == 'file':
            if not self.attachment_ids:
                raise UserError(_("When choosing 'Attach Files', you need to upload a photo or video file"))
        self.attachment_ids.generate_access_token()
        # create post list
        post_list = []
        for page in self.page_ids:
            # Create copies of attachments
            new_attachment_ids = []
            if self.attachment_ids:
                new_attachment_ids = self.attachment_ids.mapped(lambda att: att.copy().id)
            post_data = {
                'article_id': self.id,
                'page_id': page.id,
                'message': self.message,
                'attachment_ids': [(6, 0, new_attachment_ids)],
                'attachment_link': self.attachment_link,
                'attachment_link_title': self.attachment_link_title,
            }
            post_list.append(post_data)
        posts = self.env['social.post'].create(post_list)
        self.state = 'confirmed'
        link_posts = ["<a href=# data-oe-model=social.post data-oe-id=%s>%s</a>" % (post.id, post.page_id.display_name) for post in posts]
        body = _("<ul class='o_mail_thread_message_tracking'> \
                    <li>%(post_count)s Post have created: %(post_names)s </li> \
                </ul>") % {
                    'post_count': len(link_posts),
                    'post_names': ", ".join(link_posts),
                }
        self.message_post(body=Markup(body))

    def action_cancel(self):
        self.ensure_one()
        if not self.post_ids.filtered(lambda r: r.state in ('posted', 'scheduled')) and self.env.user == self.assign_id:
            self.post_ids.with_context(check_right=False).action_delete_post()
        else:
            if not self.env.user.has_group('viin_social.viin_social_group_approve'):
                raise UserError(_(
                    "You cannot delete posts already posted. You need to be in the Approve group and have permissions "
                    "with the respective Posts"))
            self.post_ids.with_context(delete_on_social=True).action_delete_post()
        self.state = 'cancelled'

    def action_view_posts(self):
        action = self.env['ir.actions.act_window']._for_xml_id('viin_social.social_post_action')
        if self.post_count != 1:
            action['domain'] = "[('article_id', '=', %s)]" % self.id
        elif self.post_count == 1:
            res = self.env.ref('viin_social.social_post_view_form', False)
            action['views'] = [(res and res.id or False, 'form')]
            action['res_id'] = self.post_ids.id
        return action

    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, **kwargs):
        # add partners to Followers list when mentioning
        if self.env.user.has_group('viin_social.viin_social_group_editor'):
            return super(SocialArticle, self.sudo().with_context(mail_post_autofollow=True)).message_post(**kwargs)
        return super(SocialArticle, self).message_post(**kwargs)

    def message_subscribe(self, partner_ids=None, subtype_ids=None):
        if self.env.user.has_group('viin_social.viin_social_group_editor'):
            return super(SocialArticle, self.sudo()).message_subscribe(partner_ids, subtype_ids)
        return super(SocialArticle, self).message_subscribe(partner_ids, subtype_ids)

    def _check_attachment_link(self):
        for r in self.filtered(lambda r: r.attachment_link):
            try:
                req = requests.get(r.attachment_link)
                req.raise_for_status()
            except Exception:
                raise UserError(_("URL Unsupported or was not found"))

    def action_update_social_post(self):
        self.ensure_one()
        pages_to_add_post = self.page_ids - self.post_ids.page_id
        pages_to_delete_post = self.post_ids.page_id - self.page_ids
        posts_to_delete = self.post_ids.filtered(lambda post: post.page_id in pages_to_delete_post)

        posts = self.post_ids - posts_to_delete
        posts_to_update = (self.post_ids - posts_to_delete).filtered(lambda post: post.state in ['scheduled', 'posted'])

        post_create_count = len(pages_to_add_post) + len(posts - posts_to_update)
        message = _('Info: \n')
        if post_create_count > 0:
            message += _("%s new posts will be posted \n") % post_create_count
        if len(pages_to_delete_post) > 0:
            message += _("%s posts will be deleted \n") % len(pages_to_delete_post)
        if len(posts_to_update) > 0:
            message += _("%s posts will be updated \n") % len(posts_to_update)

        return {
            'type': 'ir.actions.act_window',
            'name': _('Update Social Post'),
            'res_model': 'wizard.social.confirm',
            'view_mode': 'form',
            'view_id': self.env.ref('viin_social.wizard_social_confirm_view_form').id,
            'target': 'new',
            'context': {
                'message': message,
                'model': 'social.article',
                'method': 'update_social_post',
                'res_ids': self.ids
            }
        }

    def update_social_post(self):
        pages_to_add_post = self.page_ids - self.post_ids.page_id
        pages_to_delete_post = self.post_ids.page_id - self.page_ids
        posts_to_delete = self.post_ids.filtered(lambda post: post.page_id in pages_to_delete_post)
        posts_to_update = self.post_ids - posts_to_delete

        post_data = []
        for page in pages_to_add_post:
            post_data.append({
                'article_id': self.id,
                'page_id': page.id,
                'message': self.message,
                'attachment_ids': self.attachment_ids,
                'attachment_link': self.attachment_link,
                'attachment_link_title': self.attachment_link_title,
            })
        for post in self.env['social.post'].create(post_data):
            post.action_post_article()

        posts_to_delete.action_delete_post()

        posts_to_update.write({
            'message': self.message,
            'attachment_link': self.attachment_link,
            'attachment_link_title': self.attachment_link_title,
        })
        for post in posts_to_update:
            if post.state in ['posted', 'scheduled']:
                post.update_social_post()

    def action_post_article(self):
        for post in self.post_ids:
            if post.state != 'cancelled':
                post.action_post_article()

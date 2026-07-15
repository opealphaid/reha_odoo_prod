import logging

from odoo import models, fields

_logger = logging.getLogger(__name__)


class SocialMedia(models.Model):
    _name = 'social.media'
    _inherit = ['social.mixin', 'mail.thread', 'mail.activity.mixin']
    _description = 'Social Media'

    def _default_domain_user(self):
        group_approve = self.env.ref('viin_social.viin_social_group_approve', raise_if_not_found=False)
        group_approve = group_approve and [group_approve.id] or []
        user_ids = self.env['res.users'].search([('groups_id', 'in', group_approve), ('company_id', '=', self.env.company.id)])
        return [('id', 'in', user_ids.ids)]

    name = fields.Char(string='Name', required=True)
    image = fields.Image(string='Logo', help="Logo of Social Media")
    description = fields.Text(string='Description', help="Description of Social Media")
    social_provider = fields.Selection([('none', 'None')], default='none', required=True, readonly=True, string='Social Provider')
    assign_id = fields.Many2one('res.users', string='Approver', domain=_default_domain_user,
                                help="User has rights to all posts in all pages of this media on social networks")
    token_expired_date = fields.Datetime(string='Token Expired Date', help="Expiration date of access token", readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    _sql_constraints = [
        ('name_unique_per_company', "UNIQUE(name, company_id)", "Social Media name must be unique per company"),
    ]

    def action_link_account(self):
        # for inherit
        pass

    def action_synchronized(self):
        """ Synchronize data pages from a social network """
        self.ensure_one()
        self._synchronized()

    def _synchronized(self):
        """ Synchronize data pages from a social network """
        pass

    def _cron_synchronized_all_datas(self):
        group_manager = self.env.ref('viin_social.viin_social_group_admin', raise_if_not_found=False)
        user = self.env['res.users'].search([('groups_id', '=', group_manager.id)], limit=1)
        self = self.with_user(user)
        medias = self.env['social.media'].search([])
        social_providers = medias.mapped(lambda m: m.social_provider != 'none' and m.social_provider)
        for social_provider in social_providers:
            provider_medias = medias.filtered(lambda m: m.social_provider == social_provider)
            if provider_medias:
                custom_cron_synchronized_all_datas_method = '_cron_synchronized_all_datas_%s' % social_provider
                if hasattr(provider_medias, custom_cron_synchronized_all_datas_method):
                    # implement try...except during executing the custom_cron_synchronized_all_datas_method
                    # to avoid error raising in cron mode
                    try:
                        with self.env.cr.savepoint():
                            getattr(provider_medias, custom_cron_synchronized_all_datas_method)()
                    except Exception as e:
                        _logger.error(str(e))

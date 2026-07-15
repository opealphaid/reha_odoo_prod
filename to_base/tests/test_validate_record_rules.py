import logging

from odoo.tests import TransactionCase, tagged

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestValidateRecordRule(TransactionCase):

    def test_01_validate_record_rule(self):
        """Validate all rules after installation to avoid unexpected errors that affect other modules

        Tình huống:
        Group A không có quyền sửa model xyz
        Rule A áp dụng cho Group A, có áp dụng cho cả quyền write (perm_write = True hoặc không khai báo, mặc định là True)

        Group B có quyền sửa model xyz
        Rule B áp dụng cho Group B

        Nếu người dùng thuộc cả 2 group A và B, chỉ thỏa mãn Rule A, nhưng không thỏa mãn Rule B => Vẫn có quyền sửa
        Vì check group trước, sau đó check Rule là hoặc

        Mong đợi: Không có quyền sửa
        """
        def _build_msg(rule, perm):
            groups_ext = ','.join([v[0] for v in rule.groups._get_external_ids().values()])
            rule_ext = rule.get_external_id().get(rule.id, '')
            return f"'{rule_ext}' rule: You should set '{perm}=False', because '{groups_ext}' group has '{perm}=False' on model '{rule.model_id.model}'.\n"

        rules = self.env['ir.rule'].search(
            [
                ('model_id.transient', '=', False),
                ('groups', '!=', False),
                ('groups', 'not in', [self.env.ref('base.group_portal').id, self.env.ref('base.group_public').id])
            ]
        ).filtered(lambda r: r.model_id.model in self.env and self.env[r.model_id.model]._auto)

        def get_groups_implied_ids(groups):
            if groups.implied_ids:
                return groups | get_groups_implied_ids(groups.implied_ids)
            return groups

        all_model_access = self.env['ir.model.access'].search([('model_id', 'in', rules.model_id.ids), ('group_id', 'in', rules.groups.ids)])
        msg = ''
        for rule in rules:
            # ignore the rules of the module in Odoo CE
            # waiting for Odoo promotion at https://github.com/odoo/odoo/pull/169578
            if rule.get_external_id().get(rule.id, '').split('.')[0] in [
                'account',
                'account_payment',
                'auth_passkey',
                'base',
                'crm',
                'google_calendar',
                'hr',
                'hr_contract',
                'hr_expense',
                'hr_recruitment',
                'hr_recruitment_skills',
                'iap',
                'lunch',
                'maintenance',
                'microsoft_calendar',
                'point_of_sale',
                'project',
                'purchase',
                'sale',
                'sales_team',
                'spreadsheet_dashboard',
                'survey',
                'website',
                'website_crm_iap_reveal',
                'website_slides_forum',
            ]:
                continue
            model_access = self.env['ir.model.access']
            for acc in all_model_access:
                if acc.model_id != rule.model_id:
                    continue
                if acc.group_id in rule.groups or acc.group_id in get_groups_implied_ids(rule.groups.implied_ids):
                    model_access |= acc
            if not model_access:
                continue
            if rule.perm_create and rule.perm_create not in set(model_access.mapped('perm_create')):
                msg += _build_msg(rule, 'perm_create')
            if rule.perm_read and rule.perm_read not in set(model_access.mapped('perm_read')):
                msg += _build_msg(rule, 'perm_read')
            if rule.perm_write and rule.perm_write not in set(model_access.mapped('perm_write')):
                msg += _build_msg(rule, 'perm_write')
            if rule.perm_unlink and rule.perm_unlink not in set(model_access.mapped('perm_unlink')):
                msg += _build_msg(rule, 'perm_unlink')
        if msg:
            _logger.warning('\n' + msg)

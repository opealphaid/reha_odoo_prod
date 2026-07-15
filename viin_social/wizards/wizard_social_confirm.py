from odoo import models, fields


class WizardSocialConfirm(models.TransientModel):
    _name = 'wizard.social.confirm'
    _description = 'Wizard Social Confirm'

    message = fields.Text(string='Message', default=lambda self: self._context['message'], readonly=True)

    def confirm(self):
        self.ensure_one()
        model = self._context['model']
        method = self._context['method']
        res_ids = self._context['res_ids']
        return getattr(self.env[model].browse(res_ids), method)(*self._context.get('args', []), **self._context.get('kwargs', {}))

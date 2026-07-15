import ast
import base64
import re
import requests

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError


class WAComposer(models.TransientModel):
    _name = 'wa.compose.message'
    _description = 'Whatsapp composition wizard'

    @api.model
    def default_get(self, fields):
        result = super(WAComposer, self).default_get(fields)
        active_model = False
        active_id = False
        template_domain = [('state', '=', 'added')]
        # Multi Companies and Multi Providers Code Here
        if self.env.user:
            provider_id = self.env.user.provider_ids.filtered(lambda x: x.company_id == self.env.company)
            if provider_id:
                result['provider_id'] = provider_id[0].id
                template_domain += [('provider_id', '=', provider_id[0].id)]
            else:
                template = self.env['wa.template'].browse(result.get('template_id'))
                provider_id = template.provider_id
                result['provider_id'] = provider_id.id
                template_domain += [('provider_id', '=', provider_id.id)]

        if 'model' in result:
            active_model = result.get('model')
            active_id = result.get('res_id')
        else:
            active_model = self.env.context.get('active_model')
            active_id = self.env.context.get('active_id')
        if active_model:
            record = self.env[active_model].browse(active_id)
            if 'template_id' in result:
                template = self.env['wa.template'].browse(result.get('template_id'))
                result['body'] = template._render_field('body_html', [record.id], compute_lang=True)[
                    record.id]
            if active_model == 'res.partner':
                result['partner_id'] = record.id
            else:
                if record._fields.get('partner_id'):
                    result['partner_id'] = record.partner_id and record.partner_id.id or False
                else:
                    if self._context.get('default_partner_id'):
                        result['partner_id'] = self._context.get('default_partner_id')
                    else:
                        result['partner_id'] = False
            if 'report' in self.env.context:
                report = str(self.env.context.get('report'))
                if active_model == 'event.registration':
                    pdf = self.env['ir.actions.report']._render_qweb_pdf(report, record.event_id.id)
                else:
                    pdf = self.env['ir.actions.report']._render_qweb_pdf(report, record.id)
                Attachment = self.env['ir.attachment'].sudo()
                b64_pdf = base64.b64encode(pdf[0])
                name = ''
                if active_model == 'res.partner':
                    if report == 'account_followup.action_report_followup':
                        name = 'Followups-%s' % record.id
                elif active_model == 'stock.picking':
                    name = ((record.state in ('done') and _('Delivery slip - %s') % record.name) or
                            _('Picking Operations - %s') % record.name)
                elif active_model == 'account.move':
                    name = ((record.state in ('posted') and record.name) or
                            _('Draft - %s') % record.name)
                elif active_model == 'event.registration':
                    name = (record.name or
                            _('Event - %s') % record.name)
                else:
                    name = ((record.state in ('draft', 'sent') and _('Quotation - %s') % record.name) or
                            _('Order - %s') % record.name)

                name = '%s.pdf' % name
                attac_id = Attachment.search([('name', '=', name)], limit=1)
                if report == 'account_followup.action_report_followup':
                    attac_id = Attachment
                if len(attac_id) == 0:
                    attac_id = Attachment.create({'name': name,
                                                  'type': 'binary',
                                                  'datas': b64_pdf,
                                                  'res_model': active_model if active_model else 'whatsapp.history',
                                                  })
                if active_model == 'res.partner':
                    result['partner_id'] = record.id
                else:
                    if record._fields.get('partner_id'):
                        result['partner_id'] = record.partner_id.id
                    elif self._context.get('default_partner_id'):
                        partner = self.env['res.partner'].browse(self._context.get('default_partner_id'))
                        result['partner_id'] = partner.id
                    else:
                        result['partner_id'] = False
                result['attachment_ids'] = [(4, attac_id.id)]
        if active_model or self._context.get('default_model'):
            model = active_model or self._context.get('default_model')
            template_domain += [('model', '=', model)]
        template_ids = self.template_id.search(template_domain)
        self.domain_template_ids = [(6, 0, template_ids.ids)]
        return result

    body = fields.Html('Contents', default='', sanitize_style=True)
    partner_id = fields.Many2one('res.partner')
    template_id = fields.Many2one('wa.template', 'Use template', index=True)
    domain_template_ids = fields.Many2many(comodel_name='wa.template', string='domain template ids')
    attachment_ids = fields.Many2many('ir.attachment', 'wa_compose_message_ir_attachments_rel', 'wa_wizard_id',
                                      'attachment_id', 'Attachments')
    model = fields.Char('Related Document Model', index=True)
    res_id = fields.Integer('Related Document ID', index=True)
    provider_id = fields.Many2one('provider', 'Provider')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, required=True)
    allowed_provider_ids = fields.Many2many('provider', 'Provider', compute='update_allowed_providers')

    @api.depends('company_id')
    def update_allowed_providers(self):
        self.allowed_provider_ids = self.env.user.provider_ids

    @api.onchange('company_id', 'provider_id')
    def onchange_company_provider(self):
        self.template_id = False
        self.domain_template_ids = False
        domain = []
        if self._context.get('active_model') or self._context.get('default_model'):
            domain += [('model_id.model', '=', self._context.get('active_model') or self._context.get('default_model'))]
        if self.provider_id:
            domain += [('provider_id', '=', self.provider_id.id)]
        template_ids = self.template_id.search(domain)
        self.domain_template_ids = [(6, 0, template_ids.ids)]

    @api.onchange('template_id')
    def onchange_template_id_wrapper(self):
        self.ensure_one()
        if 'active_model' in self.env.context:
            active_model = str(self.env.context.get('active_model'))
            active_id = self.env.context.get('active_id') or self.env.context.get('active_ids')
            active_record = self.env[active_model].browse(active_id)
            for record in self:
                if record.template_id:
                    if record.template_id.components_ids.filtered(lambda comp: comp.type == 'body'):
                        variables_ids = record.template_id.components_ids.variables_ids
                        if variables_ids:
                            temp_body = tools.html2plaintext(record.template_id.body_html)
                            variables_length = len(record.template_id.components_ids.variables_ids)
                            for length, variable in zip(range(variables_length), variables_ids):
                                st = '{{%d}}' % (length + 1)
                                if variable.field_id.model == active_model or variable.free_text:
                                    value = active_record.read()[0][
                                        variable.field_id.name] if variable.field_id.name else variable.free_text
                                    if isinstance(value, tuple):
                                        value = value[1]
                                        temp_body = temp_body.replace(st, str(value))
                                    else:
                                        temp_body = temp_body.replace(st, str(value))
                            record.body = tools.plaintext2html(temp_body)
                        else:
                            record.body = \
                                record.template_id._render_field('body_html', [active_record.id], compute_lang=True)[
                                    active_record.id]

                else:
                    record.body = ''
        else:
            active_record = self.env[self.model].browse(self.res_id)
            for record in self:
                if record.template_id:
                    record.body = record.template_id._render_field('body_html', [active_record.id], compute_lang=True)[
                        active_record.id]
                else:
                    record.body = ''

    def send_whatsapp_message(self):
        if not (self.body or self.template_id or self.attachment_ids):
            return {}
        
        active_model = str(self.env.context.get('active_model')) if self.env.context.get('active_model', False) else self.model
        active_id = self.env.context.get('active_id') if self.env.context.get('active_id', False) else self.res_id
        record = self.env[active_model].browse(active_id)
        if active_model in ['sale.order', 'purchase.order']:
            record.filtered(lambda s: s.state == 'draft').write({'state': 'sent'})

        # Multi Companies and Multi Providers Code Here
        channel = self.provider_id.get_channel_whatsapp(self.partner_id, self.env.user)

        if channel:
            message_values = {
                'body': tools.html2plaintext(self.body) if self.body else '',
                'author_id': self.provider_id.user_id.partner_id.id,
                'email_from': self.provider_id.user_id.partner_id.email or '',
                'model': active_model,
                'message_type': 'wa_msgs',
                'isWaMsgs': True,
                'subtype_id': self.env['ir.model.data'].sudo()._xmlid_to_res_id('mail.mt_comment'),
                'partner_ids': [(4, self.provider_id.user_id.partner_id.id)],
                'res_id': active_id,
                'reply_to': self.provider_id.user_id.partner_id.email,
                'attachment_ids': [(4, attac_id.id) for attac_id in self.attachment_ids],
            }
            context_vals = {'provider_id': self.provider_id}
            if self.template_id:
                context_vals.update({'template_send': True, 'wa_template': self.template_id, 'active_model_id': active_id,
                                     'active_model': active_model, 'partner_id': self._context.get('partner_id') or self.partner_id.id,
                                     'attachment_ids': self.attachment_ids})

            mail_message = self.env['mail.message'].sudo().with_context(context_vals).create(
                message_values)
            channel._notify_thread(mail_message, message_values)
            mail_message.chatter_wa_model = active_model
            mail_message.chatter_wa_res_id = record.id

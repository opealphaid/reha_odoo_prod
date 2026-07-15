from odoo import models, fields, api, tools
from datetime import datetime


class TestWhatsappMarketing(models.TransientModel):
    _name = 'test.whatsapp.marketing'
    _description = 'Test for marketing campaigns'

    partner_id = fields.Many2one('res.partner')
    template_id = fields.Many2one('wa.template')
    body_html = fields.Html('Body')

    def test_whatsapp_marketing(self):
        for record in self:
            params = []
            if record.template_id and record.partner_id and record.template_id.provider_id:
                provider_id = record.template_id.provider_id
                if record.template_id.template_type == 'template':
                    for component in record.template_id.components_ids:
                        object_data = self.env['res.partner'].search_read(
                            [('id', '=', record.partner_id.id)])[0]

                        template_dict = {}
                        cards = []
                        if component.type in ['body', 'footer'] and component.variables_ids:
                            template_dict.update({'type': component.type})
                            parameters = []
                            for variable in component.variables_ids:
                                parameters.append(self.env['whatsapp.history']._get_variable_params_dict(variable, object_data))
                                template_dict.update({'parameters': parameters})
                        if component.type == "header":
                            if component.formate == "text" and component.variables_ids:
                                template_dict.update(
                                    {"type": component.type}
                                )
                                parameters = []
                                for variable in component.variables_ids:
                                    parameters.append(
                                        self.env['whatsapp.history']._get_variable_params_dict(variable, object_data))
                                    template_dict.update({'parameters': parameters})
                            if component.formate == "media" and component.formate_media_type in ["dynamic",
                                                                                                 "static"]:
                                if component.media_type in ["image", "document", "video"] and (
                                        self.env.context.get("attachment_ids") or component.attachment_ids):
                                    template_dict.update({"type": component.type})
                                    doc_attachment = self.env.context.get(
                                        "attachment_ids") if component.formate_media_type == "dynamic" else component.attachment_ids
                                    parameters = provider_id.get_docs_parameters(doc_type=component.media_type,
                                                                                 doc_id=fields.first(
                                                                                     doc_attachment))
                                    template_dict.update({"parameters": parameters})

                        if component.type == "buttons":
                            record.template_id._get_send_button_params(component, object_data, params)

                        if component.type == 'carousel':
                            record.template_id._get_carousel_params(component, object_data, provider_id, cards)
                        if component.type == "limited_time_offer":
                            template_dict.update({'type': component.type})
                            parameter = []
                            limited_time_offer = {
                                "type": "limited_time_offer",
                                "limited_time_offer": {
                                    'expiration_time_ms': datetime.timestamp(
                                        component.limited_offer_exp_date) * 1000
                                }
                            }
                            parameter.append(limited_time_offer)
                            template_dict.update({'parameters': parameter})
                        if bool(template_dict):
                            params.append(template_dict)
                        if cards:
                            params.append({"type": "CAROUSEL", "cards": cards})
                    provider_id.send_template(record.template_id.name, record.template_id.language,
                                              record.template_id.namespace, record.partner_id, params)
                elif record.template_id.template_type == 'interactive':
                    params = []
                    for component in record.template_id.components_ids:
                        if component.type == 'interactive':
                            template_dict = provider_id._get_interactive_template_params(component)
                            if bool(template_dict):
                                params.append(template_dict)
                    provider_id.send_mpm_template(record.template_id.name, record.template_id.language,
                                                  record.template_id.namespace, record.partner_id,
                                                  params)
                return {'effect': {'fadeout': 'slow',
                                   'message': "Whatsapp Template Sent Successfully",
                                   }
                        }

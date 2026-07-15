# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.
import json
from datetime import datetime
from odoo import api, fields, models, tools
from odoo.exceptions import UserError, ValidationError
from odoo.addons.all_in_one_whatsapp_odoo_community.tus_meta_whatsapp_base.models.whatsapp_history import image_type, video_type, audio_type, document_type


class WhatsappHistory(models.Model):
    _inherit = "whatsapp.history"

    channel_id = fields.Many2one(comodel_name="discuss.channel", string="Mail Channel")
    wa_chatbot_id = fields.Many2one(comodel_name="whatsapp.chatbot", string="Whatsapp Chatbot")

    def _send_wa_message(self, provider, channel, message):
        mail_message = self.env["mail.message"].sudo().with_user(provider.user_id.id).with_context(
            {"provider_id": provider}).create(message)
        channel._notify_thread(mail_message, message)

    def _send_wa_template(self, provider, channel, partner, template, message, active_id):
        """
        This method will create a mail message for whatsapp API.
        """
        context_dict = {
            "template_send": True,
            "wa_template": template,
            "active_model_id": active_id.id,
            "active_model": "discuss.channel",
            "active_model_id_chat_bot": active_id.id,
            "active_model_chat_bot": "res.partner",
            "provider_id": provider
        }
        wa_attach_message = self.env["mail.message"].sudo().with_user(provider.user_id.id).with_context(
            context_dict).create(message)
        channel._notify_thread(wa_attach_message, message)

    # def _get_active_chatbot(self):
    #     return self.env.company.wa_chatbot_id.id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('is_commerce_manager', False):
                return super(WhatsappHistory, self).create(vals)
            if vals.get('is_dynamic_booking_chatbot', False):
                return super(WhatsappHistory, self).create(vals)
            wa_template = self.env.context.get("wa_template")
            provider_id = self.env["provider"].browse(int(vals.get("provider_id", False)))
            partner_id = self.env["res.partner"].browse(int(vals.get("partner_id", False)))
            user = provider_id.user_id
            channel = provider_id.get_channel_whatsapp(partner_id, user)
            chatbot = provider_id.company_id.wa_chatbot_id
            if provider_id and partner_id and partner_id.mobile and channel:
                if not self.env.context.get("whatsapp_application") and not vals.get('type') == 'received':
                    if self.env.context.get("template_send", False):
                        if wa_template and wa_template.template_type == "interactive":
                            params = []
                            for component in wa_template.components_ids:
                                template_dict = provider_id._get_interactive_template_params(component)
                                if bool(template_dict):
                                    params.append(template_dict)
                            try:
                                answer = provider_id.send_mpm_template(
                                    wa_template.name,
                                    wa_template.language,
                                    wa_template.namespace,
                                    partner_id,
                                    params,
                                )
                            except UserError as e:
                                if vals.get('mail_message_id'):
                                    provider_id._get_remove_unwanted_mail_message(vals.get('mail_message_id'))
                                raise ValidationError(str(e))
                            if answer.status_code == 200:
                                dict = json.loads(answer.text)
                                if provider_id.provider == "graph_api":
                                    if dict.get("messages", False) and dict.get("messages")[0].get("id", False):
                                        mail_message = self.env['mail.message'].browse(vals.get('mail_message_id'))
                                        mail_message.wa_message_id = dict.get("messages")[0].get("id")
                                        vals['message_id'] = dict.get("messages")[0].get("id")
                                        if self.env.context.get("wa_messsage_id"):
                                            self.env.context.get("wa_messsage_id").wa_message_id = dict.get("messages")[
                                                0].get("id")
                        elif wa_template and wa_template.template_type == "template":
                            wa_template = self.env.context.get("wa_template")
                            params = []
                            if wa_template.category == 'authentication':
                                partner_id.otp_text = wa_template.generate_secure_otp(wa_template.otp_length)
                                partner_id.sudo().write({
                                    'otp_text': partner_id.otp_text,
                                    'otp_time': datetime.now(),
                                })
                            for component in wa_template.components_ids:
                                model = self.env.context.get('active_model_chat_bot') or wa_template.model_id._name
                                object_data = self.env[wa_template.model_id.model].search_read(
                                    [('id', '=', self.env.context.get('active_model_id'))])[0]

                                template_dict = {}
                                cards = []
                                if component.type in ['body', 'footer'] and component.variables_ids:
                                    template_dict.update({'type': component.type})
                                    parameters = []
                                    for variable in component.variables_ids:
                                        parameters.append(self._get_variable_params_dict(variable, object_data))
                                        template_dict.update({'parameters': parameters})
                                    for length, var in enumerate(component.variables_ids):
                                        st = '{{%d}}' % (length + 1)
                                        if var.field_id.model or var.free_text:
                                            mail_message = self.env['mail.message'].browse(
                                                vals.get('mail_message_id', None))
                                            value = object_data.get(
                                                var.field_id.name) if var.field_id.name else var.free_text
                                            if mail_message:
                                                mail_message.write({
                                                    'body': mail_message.body.replace(st, str(
                                                        value[1] if isinstance(value, tuple) else value))
                                                })
                                                vals['message'] = tools.html2plaintext(
                                                    mail_message.body.replace(st, str(
                                                        value[1] if isinstance(value, tuple) else value)))

                                if component.type == "header":
                                    if component.formate == "text" and component.variables_ids:
                                        template_dict.update(
                                            {"type": component.type}
                                        )
                                        parameters = []
                                        for variable in component.variables_ids:
                                            parameters.append(
                                                self._get_variable_params_dict(variable, object_data))
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
                                    wa_template._get_send_button_params(component, object_data, params)

                                if component.type == 'carousel':
                                    wa_template._get_carousel_params(component, object_data, provider_id, cards)
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

                            try:
                                answer = provider_id.send_template(
                                    wa_template.name,
                                    wa_template.language,
                                    wa_template.namespace,
                                    partner_id,
                                    params,
                                )
                            except UserError as e:
                                if vals.get('mail_message_id'):
                                    provider_id._get_remove_unwanted_mail_message(vals.get('mail_message_id'))
                                raise ValidationError(str(e))
                            if answer.status_code == 200:
                                dict = json.loads(answer.text)
                                if provider_id.provider == "graph_api":
                                    if dict.get("messages", False) and dict.get("messages")[0].get("id"):
                                        mail_message = self.env['mail.message'].browse(vals.get('mail_message_id'))
                                        mail_message.wa_message_id = dict.get("messages")[0].get("id")
                                        vals['message_id'] = dict.get("messages")[0].get("id")

                                        if self.env.context.get("wa_messsage_id"):
                                            self.env.context.get(
                                                "wa_messsage_id"
                                            ).wa_message_id = dict.get("messages")[
                                                0
                                            ].get(
                                                "id"
                                            )

                    else:
                        if vals.get("message"):
                            if "message_parent_id" in self.env.context:
                                parent_msg = self.env["mail.message"].sudo().search(
                                    [("id", "=", self.env.context.get("message_parent_id").id)])
                                answer = provider_id.send_message(partner_id, vals.get("message"),
                                                                  parent_msg.wa_message_id)
                            else:
                                answer = provider_id.send_message(partner_id, vals.get("message"))
                                if answer and provider_id.company_id.is_chatbot_ended and channel.script_sequence != 1 and not vals['message_id']:
                                    channel.is_chatbot_ended = True
                                else:
                                    channel.is_chatbot_ended = False

                            if answer.status_code == 200:
                                dict = json.loads(answer.text)
                                if provider_id.provider == "graph_api":
                                    if dict.get("messages", False) and dict.get("messages")[0].get("id"):
                                        mail_message = self.env['mail.message'].browse(vals.get('mail_message_id'))
                                        mail_message.wa_message_id = dict.get("messages")[0].get("id")
                                        vals['message_id'] = dict.get("messages")[0].get("id")
                                        if self.env.context.get(
                                                "wa_messsage_id"
                                        ):
                                            self.env.context.get(
                                                "wa_messsage_id"
                                            ).wa_message_id = dict.get(
                                                "messages"
                                            )[
                                                0
                                            ].get(
                                                "id"
                                            )

                        if vals.get("attachment_ids"):
                            for attachment in vals.get("attachment_ids"):
                                if attachment[1]:
                                    attachment_id = (
                                        self.env["ir.attachment"]
                                        .sudo()
                                        .browse(attachment[1])
                                    )

                                    if provider_id.provider == "graph_api":
                                        sent_type = ''
                                        if attachment_id.mimetype in image_type:
                                            sent_type += "image"
                                        elif (
                                                attachment_id.mimetype
                                                in document_type
                                        ):
                                            sent_type += "document"
                                        elif (
                                                attachment_id.mimetype in audio_type
                                        ):
                                            sent_type += "audio"
                                        elif (
                                                attachment_id.mimetype in video_type
                                        ):
                                            sent_type += "video"
                                        else:
                                            sent_type += "image"

                                        answer = provider_id.send_image(
                                            attachment_id
                                        )
                                        if answer.status_code == 200:
                                            dict = json.loads(answer.text)
                                            media_id = dict.get("id")
                                            if 'message_parent_id' in self.env.context:
                                                parent_msg = self.env['mail.message'].sudo().search(
                                                    [('id', '=', self.env.context.get('message_parent_id').id)])
                                                getimagebyid = (
                                                    provider_id.get_image_by_id(
                                                        media_id,
                                                        partner_id,
                                                        sent_type,
                                                        attachment_id,
                                                        parent_msg.wa_message_id
                                                    )
                                                )
                                            else:
                                                getimagebyid = (
                                                    provider_id.get_image_by_id(
                                                        media_id,
                                                        partner_id,
                                                        sent_type,
                                                        attachment_id,
                                                    )
                                                )
                                            if getimagebyid.status_code == 200:
                                                imagedict = json.loads(
                                                    getimagebyid.text
                                                )
                                            if (
                                                    "messages" in imagedict
                                                    and imagedict.get("messages")
                                            ):
                                                vals[
                                                    "message_id"
                                                ] = imagedict.get('messages')[0].get('id', '')
                                                if self.env.context.get(
                                                        "wa_messsage_id"
                                                ):
                                                    self.env.context.get(
                                                        "wa_messsage_id"
                                                    ).wa_message_id = imagedict.get('messages')[0].get('id', '')
                                            else:
                                                if not self.env.context.get(
                                                        "cron"
                                                ):
                                                    if "messages" in imagedict:
                                                        raise UserError(
                                                            imagedict.get(
                                                                "message"
                                                            )
                                                        )
                                                    if "error" in imagedict:
                                                        raise UserError(
                                                            imagedict.get(
                                                                "error"
                                                            ).get("message")
                                                        )
                                                else:
                                                    vals.update(
                                                        {"type": "fail"}
                                                    )
                                                    if "messages" in imagedict:
                                                        vals.update(
                                                            {
                                                                "fail_reason": imagedict.get(
                                                                    "message"
                                                                )
                                                            }
                                                        )

                vals.update({"is_chatbot": True})
                res = super(WhatsappHistory, self).create(vals)
                if res.message_id and res.type == 'in queue':
                    res.type = 'sent'
                res.mail_message_id.wa_message_id = res.message_id if not res.mail_message_id.wa_message_id else res.mail_message_id.wa_message_id

                if vals.get("message") and vals.get("type") == "received":
                    if provider_id.company_id and provider_id.company_id.wa_chatbot_id:
                        # Bot
                        if not channel.is_chatbot_ended:
                            if res.type == 'received' and res.mail_message_id:
                                # Read messages because chatbot is working.
                                provider_id.graph_api_wamsg_mark_as_read(res.mail_message_id.wa_message_id)
                                res.mail_message_id.wp_status = 'read'
                            message_script = chatbot.mapped("step_type_ids").mapped(
                                'multi_script_chatbot_ids').filtered(
                                lambda script_message: script_message.message_for_multi_script == vals.get(
                                    'message')).wa_chatbot_script_id
                            current__chat_seq_script = chatbot.mapped("step_type_ids").filtered(
                                lambda l: l.sequence == channel.script_sequence)
                            if message_script:
                                chatbot_script_lines = message_script
                            elif current__chat_seq_script and not current__chat_seq_script.step_call_type == "action":
                                chatbot_script_lines = current__chat_seq_script
                            else:
                                chatbot_script_lines = provider_id.company_id.wa_chatbot_id.step_type_ids[0]

                            for chat in chatbot_script_lines:
                                if chat.sequence >= channel.script_sequence:
                                    channel.write(
                                        {
                                            "wa_chatbot_id": chat.whatsapp_chatbot_id.id if provider_id.company_id and provider_id.company_id.wa_chatbot_id == chat.whatsapp_chatbot_id else
                                            False,
                                            "script_sequence": chat.sequence,
                                        }
                                    )
                                elif (
                                        current__chat_seq_script
                                        and current__chat_seq_script.parent_id
                                        and current__chat_seq_script.parent_id
                                        == chat.parent_id
                                ):
                                    channel.write(
                                        {
                                            "wa_chatbot_id": chat.whatsapp_chatbot_id.id,
                                            "script_sequence": chat.sequence,
                                        }
                                    )
                                else:
                                    first_script = chatbot.mapped("step_type_ids").filtered(lambda l: l.sequence == 1)
                                    if first_script:
                                        channel.write(
                                            {
                                                "wa_chatbot_id": chat.whatsapp_chatbot_id.id,
                                                "script_sequence": first_script.sequence,
                                            }
                                        )
                                    else:
                                        channel.write(
                                            {
                                                "wa_chatbot_id": chat.whatsapp_chatbot_id.id if provider_id.company_id and provider_id.company_id.wa_chatbot_id == chat.whatsapp_chatbot_id
                                                else False,
                                                "script_sequence": chat.sequence,
                                            })

                                message_values = {
                                    "author_id": user.partner_id.id,
                                    "email_from": user.partner_id.email or "",
                                    "model": "discuss.channel",
                                    "message_type": "wa_msgs",
                                    "wa_message_id": vals.get("message_id"),
                                    "isWaMsgs": True,
                                    "subtype_id": self.env["ir.model.data"]
                                    .sudo()
                                    ._xmlid_to_res_id("mail.mt_comment"),
                                    "partner_ids": [(4, partner_id.id)],
                                    "res_id": channel.id,
                                    "reply_to": partner_id.email,
                                    "company_id": vals.get("company_id"),
                                    "wa_chatbot_id": chat.whatsapp_chatbot_id.id,
                                }
                                if chat.step_call_type == "message":
                                    chat_answer = chat.answer
                                    message_values.update({'body': chat_answer})
                                    self._send_wa_message(provider_id, channel, message_values)

                                if chat.step_call_type in ["template", "interactive"]:
                                    template = chat.template_id
                                    if not self.env.context.get("whatsapp_application"):
                                        if template and template.body_html != "":
                                            message_values.update({
                                                "body": tools.html2plaintext(
                                                    template.body_html)
                                            })
                                            self._send_wa_template(provider_id, channel, partner_id, template,
                                                                   message_values, partner_id)

                                if chat.step_call_type == "action" and chat.action_id:
                                    if chat.action_id.binding_model_id.model == "crm.lead":
                                        lead = (
                                            self.env["crm.lead"]
                                            .with_user(provider_id.user_id.id)
                                            .sudo()
                                            .create(
                                                {
                                                    "name": partner_id.name
                                                            + " WA ChatBot Lead",
                                                    "partner_id": partner_id.id,
                                                    "mobile": partner_id.mobile,
                                                    "user_id": provider_id.user_id.id,
                                                    "type": "lead",
                                                    "description": "Lead Description",
                                                }
                                            )
                                        )
                                        if chat.action_id.last_message_conf == 'message':
                                            last_message = chat.action_id.message
                                            message_values.update({'body': last_message})
                                            self._send_wa_message(provider_id, channel, message_values)
                                        elif chat.action_id.last_message_conf == 'template':
                                            last_message = chat.action_id.wa_template_id
                                            message_values.update({
                                                "body": tools.html2plaintext(
                                                    last_message.body_html)
                                            })
                                            self._send_wa_template(provider_id, channel, partner_id,
                                                                   last_message,
                                                                   message_values, lead)
                                        else:
                                            last_message = "Your lead have been created successfully"
                                            message_values.update({'body': last_message})
                                            self._send_wa_message(provider_id, channel, message_values)
                                        if lead:
                                            chatbot._assign_active_operator(provider_id, channel)

                                    if chat.action_id.binding_model_id.model == "helpdesk.ticket":
                                        ticket = self.env["helpdesk.ticket"].with_user(
                                            provider_id.user_id.id).sudo().create({
                                            "name": partner_id.name + " WA ChatBot Ticket ",
                                            "partner_id": partner_id.id,
                                            "partner_email": partner_id.email if partner_id.email else False,
                                            "user_id": provider_id.user_id.id,
                                            "description": "Ticket Description",
                                        })

                                        if chat.action_id.last_message_conf == 'message':
                                            last_message = chat.action_id.message
                                            message_values.update({'body': last_message})
                                            self._send_wa_message(provider_id, channel, message_values)
                                        elif chat.action_id.last_message_conf == 'template':
                                            last_message = chat.action_id.wa_template_id
                                            message_values.update({
                                                "body": tools.html2plaintext(
                                                    last_message.body_html)
                                            })
                                            self._send_wa_template(provider_id, channel, partner_id,
                                                                   last_message,
                                                                   message_values, ticket)
                                        else:
                                            last_message = "Your ticket have been generated successfully"
                                            message_values.update({'body': last_message})
                                            self._send_wa_message(provider_id, channel, message_values)
                                        if ticket:
                                            chatbot._assign_active_operator(provider_id, channel)

                                    if chat.action_id.binding_model_id.model == "discuss.channel":
                                        available_operator = chatbot._assign_active_operator(provider_id, channel)
                                        if available_operator:
                                            channel._broadcast(channel.channel_member_ids.mapped('partner_id').ids)
                                            if chat.action_id.last_message_conf == 'message':
                                                last_message = chat.action_id.message
                                                message_values.update({'body': last_message})
                                                self._send_wa_message(provider_id, channel, message_values)
                                            elif chat.action_id.last_message_conf == 'template':
                                                last_message = chat.action_id.wa_template_id
                                                message_values.update({
                                                    "body": tools.html2plaintext(
                                                        last_message.body_html)
                                                })
                                                self._send_wa_template(provider_id, channel, partner_id,
                                                                       last_message,
                                                                       message_values, channel)
                                            else:
                                                last_message = "We are getting you our expert please wait, You are now chatting with " + available_operator.name
                                                message_values.update({'body': last_message})
                                                self._send_wa_message(provider_id, channel, message_values)

                                        else:
                                            if chat.action_id.no_operator_conf == 'message':
                                                last_message = chat.action_id.no_operator_message
                                                message_values.update({'body': last_message})
                                                self._send_wa_message(provider_id, channel, message_values)
                                            elif chat.action_id.no_operator_conf == 'template':
                                                last_message = chat.action_id.no_operator_template
                                                message_values.update({
                                                    "body": tools.html2plaintext(
                                                        last_message.body_html)
                                                })
                                                self._send_wa_template(provider_id, channel, partner_id,
                                                                       last_message,
                                                                       message_values, channel)
                                            else:
                                                last_message = "Sorry, no active Operator currently available, We will getting you soon."
                                                message_values.update({'body': last_message})
                                                self._send_wa_message(provider_id, channel, message_values)

            else:
                res = super(WhatsappHistory, self).create(vals)
                if res.message_id and res.type == 'in queue':
                    res.type = 'sent'
                res.mail_message_id.wa_message_id = res.message_id if not res.mail_message_id.wa_message_id else res.mail_message_id.wa_message_id
            return res

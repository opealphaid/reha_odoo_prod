/* @odoo-module */

import { Chatter } from "@mail/chatter/web_portal/chatter";
import { Composer } from "@mail/core/common/composer";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { prettifyMessageContent } from "@mail/utils/common/format";

patch(Chatter.prototype, {
    OpenWhatsappComposer() {
        var self = this
         this.env.services.action.doAction(
            {
                type: 'ir.actions.act_window',
                res_model: 'wa.compose.message',
                view_mode: 'form',
                views: [[false, 'form']],
                target: 'new',
                context: {
                    active_model: this.props.threadModel,
                    active_id: this.props.threadId,
                },
            },
            { onClose: () => {
                self.threadService.fetchNewMessages(
                self.threadService.getThread(self.props.threadModel, self.props.threadId)
                );
              }
            }
        );
    },
});


//patch(Composer.prototype, {
//    get placeholder() {
////        if (this.thread && this.thread.model !== "discuss.channel" && !this.props.placeholder) {
//            if (this.props.type === "WaMessage") {
//                return _t("Send WhatsApp Message…");
//            }
////        }
//        return super.placeholder;
//    },
//    async onClickFullComposer(ev) {
//    debugger;
//        if (this.props.type !== "note") {
//            // auto-create partners of checked suggested partners
//            const emailsWithoutPartners = this.thread.suggestedRecipients
//                .filter((recipient) => recipient.checked && !recipient.persoa)
//                .map((recipient) => recipient.email);
//            if (emailsWithoutPartners.length !== 0) {
//                const partners = await this.rpc("/mail/partner/from_email", {
//                    emails: emailsWithoutPartners,
//                });
//                for (const index in partners) {
//                    const partnerData = partners[index];
//                    const persona = this.store.Persona.insert({ ...partnerData, type: "partner" });
//                    const email = emailsWithoutPartners[index];
//                    const recipient = this.thread.suggestedRecipients.find(
//                        (recipient) => recipient.email === email
//                    );
//                    Object.assign(recipient, { persona });
//                }
//            }
//        }
//       const attachmentIds = this.props.composer.attachments.map((attachment) => attachment.id);
//       var action = {};
//       if (this.props.type == "WaMessage") {
//            const context = {
//                default_attachment_ids: attachmentIds,
//                default_model: this.thread.model,
//                default_partner_ids:
//                    this.props.type === "WaMessage"
//                        ? []
//                        : this.thread.suggestedRecipients
//                              .filter((recipient) => recipient.checked)
//                              .map((recipient) => recipient.persona.id),
//                default_res_id: this.thread.id,
//            };
//            action = {
//                type: 'ir.actions.act_window',
//                res_model: 'wa.compose.message',
//                view_mode: 'form',
//                views: [[false, 'form']],
//                target: 'new',
//                context: context,
//            };
//        }
//        else{
////        const attachmentIds = this.props.composer.attachments.map((attachment) => attachment.id);
//        const body = this.props.composer.textInputContent;
//        const validMentions = this.store.user
//            ? this.messageService.getMentionsFromText(body, {
//                  mentionedChannels: this.props.composer.mentionedChannels,
//                  mentionedPartners: this.props.composer.mentionedPartners,
//              })
//            : undefined;
//        const context = {
//            default_attachment_ids: attachmentIds,
//            default_body: await prettifyMessageContent(body, validMentions),
//            default_model: this.thread.model,
//            default_partner_ids:
//                this.props.type === "note"
//                    ? []
//                    : this.thread.suggestedRecipients
//                          .filter((recipient) => recipient.checked)
//                          .map((recipient) => recipient.persona.id),
//            default_res_ids: [this.thread.id],
//            default_subtype_xmlid: this.props.type === "note" ? "mail.mt_note" : "mail.mt_comment",
//            mail_post_autofollow: this.thread.hasWriteAccess,
//        };
//        action = {
//            name: this.props.type === "note" ? _t("Log note") : _t("Compose Email"),
//            type: "ir.actions.act_window",
//            res_model: "mail.compose.message",
//            view_mode: "form",
//            views: [[false, "form"]],
//            target: "new",
//            context: context,
//        };
//        }
//        const options = {
//            onClose: (...args) => {
//                // args === [] : click on 'X'
//                // args === { special: true } : click on 'discard'
//                const isDiscard = args.length === 0 || args[0]?.special;
//                // otherwise message is posted (args === [undefined])
//                if (!isDiscard && this.props.composer.thread.type === "mailbox") {
//                    this.notifySendFromMailbox();
//                }
//                this.clear();
//                this.props.messageToReplyTo?.cancel();
//                if (this.thread) {
//                    this.threadService.fetchNewMessages(this.thread);
//                }
//            },
//        };
//        await this.env.services.action.doAction(action, options);
//    },
//    async sendMessage() {
//        if (this.props.composer.message) {
//            this.editMessage();
//            return;
//        }
//        await this.processMessage(async (value) => {
//            let postData = {
//                attachments: this.props.composer.attachments,
//                mentionedChannels: this.props.composer.mentionedChannels,
//                mentionedPartners: this.props.composer.mentionedPartners,
//                cannedResponseIds: this.props.composer.cannedResponses.map((c) => c.id),
//                parentId: this.props.messageToReplyTo?.message?.id,
//            };
//            if(this.props.type === "WaMessage") {
//                const new_postData = {...postData, 'isWhatsapp': this.props.type === "WaMessage", 'message_type': 'wa_msgs'}
//                await this._sendMessage(value, new_postData);
//            }else{
//                const new_postData = {...postData, 'isNote': this.props.type === "note" }
//                await this._sendMessage(value, new_postData);
//            }
//        });
////        await this.processMessage(async (value) => {
////        let postData;
////        var isWhatsapp = false
////
//////        debugger;
////        if(this.props.type === "WaMessage"){
////            postData = {
////                attachment_ids: this.props.composer.attachments,
////                isWhatsapp: this.props.type === "WaMessage",
////                message_type: 'wa_msgs',
////                mentionedChannels: this.props.composer.mentionedChannels,
////                mentionedPartners: this.props.composer.mentionedPartners,
////                cannedResponseIds: this.props.composer.cannedResponses.map((c) => c.id),
////                parentId: this.props.messageToReplyTo?.message?.id,
////            };
////        }
////        else{
////            const postData = {
////                attachments: this.props.composer.attachments,
////                isNote: this.props.type === "note",
////                mentionedChannels: this.props.composer.mentionedChannels,
////                mentionedPartners: this.props.composer.mentionedPartners,
////                cannedResponseIds: this.props.composer.cannedResponses.map((c) => c.id),
////                parentId: this.props.messageToReplyTo?.message?.id,
////            };
////        }
////        await this._sendMessage(value, postData);
////        });
//    }
//});
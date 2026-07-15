/* @odoo-module */

import { Thread } from "@mail/core/common/thread_model";

import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    get autoOpenChatWindowOnNewMessage() {
        return this.channel_type === "social_chat" || super.autoOpenChatWindowOnNewMessage;
    },

    get typesAllowingCalls() {
        return super.typesAllowingCalls.concat(["social_chat"]);
    },

    get isChatChannel() {
        return this.channel_type === "social_chat" || super.isChatChannel;
    },
});

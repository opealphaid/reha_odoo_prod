/* @odoo-module */

import { reactive } from "@odoo/owl";

import { registry } from "@web/core/registry";

export class SocialChatCoreWeb {
    constructor(env, services) {
        Object.assign(this, {
            busService: services.bus_service,
        });
        /** @type {import("@mail/core/common/store_service").Store} */
        this.store = services["mail.store"];
    }

    setup() {
        this.store.isReady.then(() => {
            if (this.store.discuss?.social_chat && this.store.settings?.is_discuss_sidebar_category_social_chat_open) {
                this.store.discuss.social_chat.isOpen = true;
            }
            this.busService.subscribe("res.users.settings", (payload) => {
                if (payload && this.store.discuss?.social_chat) {
                    this.store.discuss.social_chat.isOpen =
                        payload.is_discuss_sidebar_category_social_chat_open ??
                        this.store.discuss.social_chat.isOpen;
                }
            });
        });
    }
}

export const socialChatCoreWeb = {
    dependencies: ["bus_service", "mail.store"],
    start(env, services) {
        const socialChatCoreWeb = reactive(new SocialChatCoreWeb(env, services));
        socialChatCoreWeb.setup();
        return socialChatCoreWeb;
    },
};

registry.category("services").add("social_chat.core.web", socialChatCoreWeb);

import { Record } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { imageUrl } from "@web/core/utils/urls";

import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    setup() {
        super.setup(...arguments);
        this.appAsSocialchats = Record.one("DiscussApp", {
            compute() {
                return this.channel_type === "social_chat" ? this.store.discuss : null;
            },
        });
    },
    _computeDiscussAppCategory() {
        if (this.channel_type !== "social_chat") {
            return super._computeDiscussAppCategory();
        }
        return this.appAsSocialchats?.defaultSocialchatCategory;
    },
    get hasMemberList() {
        return this.channel_type === "social_chat" || super.hasMemberList;
    },
    get canLeave() {
        return this.channel_type !== "social_chat" && super.canLeave;
    },
    get canUnpin() {
        if (this.channel_type === "social_chat") {
            return !this.selfMember || this.selfMember.message_unread_counter === 0;
        }
        return super.canUnpin;
    },

    get avatarUrl() {
        if (this.channel_type === "social_chat") {
            return imageUrl("discuss.channel", this.id, "avatar_128");
        }
        return super.avatarUrl;
    },

});

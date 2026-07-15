import { DiscussApp } from "@mail/core/public_web/discuss_app_model";
import { Record } from "@mail/core/common/record";

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(DiscussApp.prototype, {
    setup(env) {
        super.setup(env);
        this.defaultSocialchatCategory = Record.one("DiscussAppCategory", {
            compute() {
                return {
                    extraClass: "o-mail-DiscussSidebarCategory-social-chat",
                    icon: "fa fa-comments",
                    hideWhenEmpty: true,
                    id: `social_chat`,
                    name: _t("Social Conversation"),
                    sequence: 21,
                };
            },
        });
        this.socialchats = Record.many("Thread", { inverse: "appAsSocialchats" });
    },
});

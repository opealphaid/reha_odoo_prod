{
    'name': "Facebook Social Marketing",
    'name_vi_VN': "Facebook Social Marketing",

    'summary': """
Integrate the Social Marketing app with Facebook
""",

    'summary_vi_VN': """
Tích hợp ứng dụng Social Marketing với Facebook
""",

    'description': """
Demo video: `Facebook Social Marketing <https://youtu.be/1uGSRsZpT3o>`_

Overview
========
Facebook Social Marketing helps you manage Facebook content directly from the Social Marketing app. This module allows you to create, preview, publish posts, as well as monitor interactions and respond to messages and comments without leaving the system.

Key Features
============
1. **Facebook Content Management**

   - Manage all Facebook content in an intuitive interface.

2. **Content Creation Tools**

   - Attach files, preview and publish posts.

3. **Post Progress Tracking**

   - Manage post status (Draft, Confirmed, Canceled) and assignees.

4. **Content Editing and Interaction**

   - Edit, share, delete posts directly in the app.
   - Reply to, delete, hide comments.
   - Receive and respond to Facebook messages directly.

5. **Data Synchronization**

   - Sync posts and notifications from Facebook into the system.

Benefits
========
1. **Time Saving**

   - Help manage Facebook content quickly and efficiently.

2. **Enhanced Interaction Performance**

   - Support message and comment responses within the system.

3. **Strict Content Control**

   - Synchronize and control content on a single platform.

4. **Reduced Risk of Loss of Control**

   - Help businesses maintain accurate and consistent content.

Target Users
============
1. **Businesses Using Facebook**

   - Suitable for businesses wanting to promote their brand.

2. **Marketing Teams**

   - Optimize social media content management.

3. **Campaign Managers**

   - Track Facebook campaign effectiveness more easily.

Note
====
You need to verify access permissions on Facebook before using this module, including:

- pages_show_list
- pages_read_engagement
- pages_manage_posts
- pages_read_user_content
- pages_manage_engagement
- pages_manage_metadata
- pages_messaging (optional)

Supported Editions
==================
1. **Community Edition**

    """,

    'description_vi_VN': """
Demo video: `Facebook Social Marketing <https://youtu.be/1uGSRsZpT3o>`_

Tổng quan
=========
Facebook Social Marketing giúp bạn quản lý nội dung trên Facebook trực tiếp từ ứng dụng Social Marketing. Module này cho phép tạo, xem trước, đăng bài viết, cũng như theo dõi tương tác và trả lời tin nhắn, bình luận mà không cần rời khỏi hệ thống.

Tính năng chính
===============
1. **Quản lý nội dung Facebook**

   - Quản lý toàn bộ nội dung Facebook trong một giao diện trực quan.

2. **Công cụ sáng tạo nội dung**

   - Đính kèm tệp, xem trước và đăng bài viết.

3. **Theo dõi tiến độ bài viết**

   - Quản lý trạng thái bài viết (Dự thảo, Đã xác nhận, Đã huỷ) và người chịu trách nhiệm.

4. **Chỉnh sửa và tương tác nội dung**

   - Chỉnh sửa, chia sẻ, xoá bài đăng ngay trong ứng dụng.
   - Trả lời, xoá, ẩn bình luận.
   - Nhận và phản hồi tin nhắn Facebook trực tiếp.

5. **Đồng bộ hóa dữ liệu**

   - Đồng bộ hoá bài đăng và thông báo từ Facebook vào hệ thống.

Lợi ích
=======
1. **Tiết kiệm thời gian**

   - Giúp quản lý nội dung trên Facebook một cách nhanh chóng và hiệu quả.

2. **Nâng cao hiệu suất tương tác**

   - Hỗ trợ phản hồi tin nhắn và bình luận ngay trong hệ thống.

3. **Kiểm soát nội dung chặt chẽ**

   - Đồng bộ hoá và kiểm soát nội dung trên một nền tảng duy nhất.

4. **Giảm rủi ro mất kiểm soát**

   - Giúp doanh nghiệp duy trì nội dung chính xác và nhất quán.

Đối tượng sử dụng
=================
1. **Doanh nghiệp sử dụng Facebook**

   - Phù hợp cho các doanh nghiệp muốn quảng bá thương hiệu.

2. **Nhóm Marketing**

   - Hỗ trợ tối ưu quản lý nội dung mạng xã hội.

3. **Nhà quản lý chiến dịch**

   - Theo dõi hiệu quả chiến dịch Facebook dễ dàng hơn.

Lưu ý
=====
Để sử dụng module này, doanh nghiệp cần xác minh quyền truy cập trên Facebook, bao gồm:

- pages_show_list
- pages_read_engagement
- pages_manage_posts
- pages_read_user_content
- pages_manage_engagement
- pages_manage_metadata
- pages_messaging (tùy chọn)

Ấn bản được hỗ trợ
==================
1. **Community Edition**

    """,

    'author': "Viindoo",
    'website': "https://viindoo.com/apps/app/17.0/viin_social_facebook",
    'live_test_url': "https://v17demo-int.viindoo.com",
    'live_test_url_vi_VN': "https://v17demo-vn.viindoo.com",
    'demo_video_url': "https://youtu.be/1uGSRsZpT3o",
    'support': "apps.support@viindoo.com",
    'category': 'Marketing/Social Marketing',
    'version': '0.2',

    # any module necessary for this one to work correctly
    'depends': ['viin_social'],
    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'data/media_data.xml',
        'data/ir_config_parameter_data.xml',
        'views/res_config_settings_views.xml',
        'views/social_media_views.xml',
        'views/social_page_views.xml',
        'views/social_article_views.xml',
        'views/social_post_views.xml',
        'views/social_facebook_preview_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'viin_social_facebook/static/src/scss/*'
        ],
    },
    'images': [
        'static/description/main_screenshot.png'
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': True,
    'price': 139.23,
    'subscription_price': 9.9,
    'currency': 'EUR',
    'license': 'OPL-1',
}

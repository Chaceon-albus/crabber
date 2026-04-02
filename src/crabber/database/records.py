from tortoise import fields, models


class GiftRecord(models.Model):
    id = fields.IntField(pk=True)
    room_id = fields.IntField()
    user = fields.CharField(max_length=255)
    uid = fields.IntField(default=-1)
    gift = fields.CharField(max_length=255)
    num = fields.IntField()
    value = fields.DecimalField(max_digits=12, decimal_places=2)
    comment = fields.CharField(max_length=1024, default="")
    timestamp = fields.IntField()

    class Meta(models.Model.Meta):
        table = "gift_record"


class DanmakuRecord(models.Model):
    id = fields.IntField(pk=True)
    room_id = fields.IntField()
    user = fields.CharField(max_length=255)
    uid = fields.IntField(default=-1)
    content = fields.CharField(max_length=1024)
    timestamp = fields.IntField()

    class Meta(models.Model.Meta):
        table = "danmaku_record"


class LiveRecord(models.Model):
    id = fields.IntField(pk=True)
    room_id = fields.IntField()
    title = fields.CharField(max_length=255)
    area = fields.CharField(max_length=255)
    cover_url = fields.CharField(max_length=1024)
    start_time = fields.IntField()
    end_time = fields.IntField()
    offline_gift_revenue = fields.DecimalField(max_digits=12, decimal_places=2, default=0)
    offline_guard_revenue = fields.DecimalField(max_digits=12, decimal_places=2, default=0)
    offline_sc_revenue = fields.DecimalField(max_digits=12, decimal_places=2, default=0)
    gift_revenue = fields.DecimalField(max_digits=12, decimal_places=2, default=0)
    guard_revenue = fields.DecimalField(max_digits=12, decimal_places=2, default=0)
    sc_revenue = fields.DecimalField(max_digits=12, decimal_places=2, default=0)
    summary = fields.TextField(default="")
    details = fields.JSONField(default={})

    class Meta(models.Model.Meta):
        table = "live_record"

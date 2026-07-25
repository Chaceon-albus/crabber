"""Decode Bilibili gift event payloads."""

import base64
import binascii
from typing import Any


_MAX_SEND_GIFT_V2_BYTES = 1024 * 1024
_MAX_PROTOBUF_FIELDS = 10_000
_MAX_PROTOBUF_FIELD_NUMBER = (1 << 29) - 1

type _ProtobufValue = int | bytes
type _ProtobufMessage = dict[int, list[_ProtobufValue]]


class SendGiftV2DecodeError(ValueError):
    pass


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0

    for index in range(10):
        if offset >= len(data):
            raise SendGiftV2DecodeError("truncated protobuf varint")

        byte = data[offset]
        offset += 1

        if index == 9 and byte > 1:
            raise SendGiftV2DecodeError("protobuf varint exceeds 64 bits")

        value |= (byte & 0x7f) << (index * 7)
        if not byte & 0x80:
            return value, offset

    raise SendGiftV2DecodeError("protobuf varint is too long")


def _decode_protobuf(data: bytes) -> _ProtobufMessage:
    fields: _ProtobufMessage = {}
    offset = 0
    field_count = 0

    while offset < len(data):
        field_count += 1
        if field_count > _MAX_PROTOBUF_FIELDS:
            raise SendGiftV2DecodeError("protobuf contains too many fields")

        tag, offset = _read_varint(data, offset)
        field_number = tag >> 3
        wire_type = tag & 0x07

        if not 0 < field_number <= _MAX_PROTOBUF_FIELD_NUMBER:
            raise SendGiftV2DecodeError(f"invalid protobuf field number: {field_number}")

        match wire_type:
            case 0:
                value, offset = _read_varint(data, offset)

            case 1:
                end = offset + 8
                if end > len(data):
                    raise SendGiftV2DecodeError("truncated protobuf fixed64 field")
                value = data[offset:end]
                offset = end

            case 2:
                length, offset = _read_varint(data, offset)
                end = offset + length
                if end > len(data):
                    raise SendGiftV2DecodeError("truncated protobuf bytes field")
                value = data[offset:end]
                offset = end

            case 5:
                end = offset + 4
                if end > len(data):
                    raise SendGiftV2DecodeError("truncated protobuf fixed32 field")
                value = data[offset:end]
                offset = end

            case _:
                raise SendGiftV2DecodeError(f"unsupported protobuf wire type: {wire_type}")

        fields.setdefault(field_number, []).append(value)

    return fields


def _get_int(message: _ProtobufMessage, field_number: int, default: int) -> int:
    values = message.get(field_number, [])
    if not values or not isinstance(values[0], int):
        return default

    return values[0]


def _get_text(message: _ProtobufMessage, field_number: int, default: str) -> str:
    values = message.get(field_number, [])
    if not values or not isinstance(values[0], bytes):
        return default

    try:
        return values[0].decode("utf-8")
    except UnicodeDecodeError as e:
        raise SendGiftV2DecodeError(
            f"protobuf field {field_number} is not valid UTF-8",
        ) from e


def parse_send_gift_v2(pb: str) -> list[dict[str, Any]]:
    """Decode SEND_GIFT_V2 protobuf data into legacy SEND_GIFT-like records."""

    if not isinstance(pb, str) or not pb:
        raise SendGiftV2DecodeError("SEND_GIFT_V2 pb must be a non-empty string")

    max_base64_length = ((_MAX_SEND_GIFT_V2_BYTES + 2) // 3) * 4
    if len(pb) > max_base64_length:
        raise SendGiftV2DecodeError("SEND_GIFT_V2 pb is too large")

    try:
        payload = base64.b64decode(pb, validate=True)
    except (binascii.Error, ValueError) as e:
        raise SendGiftV2DecodeError("SEND_GIFT_V2 pb is not valid base64") from e

    if len(payload) > _MAX_SEND_GIFT_V2_BYTES:
        raise SendGiftV2DecodeError("SEND_GIFT_V2 pb is too large")

    message = _decode_protobuf(payload)
    uid = _get_int(message, 1, -1)
    uname = _get_text(message, 2, "[unknown]")
    face = _get_text(message, 3, "")

    gifts = []
    for encoded_gift in message.get(10, []):
        if not isinstance(encoded_gift, bytes):
            continue

        gift = _decode_protobuf(encoded_gift)
        gifts.append({
            "uid": uid,
            "uname": uname,
            "sender_uinfo": {
                "uid": uid,
                "base": {
                    "name": uname,
                    "face": face,
                },
            },
            "gift_id": _get_int(gift, 1, -1),
            "giftName": _get_text(gift, 2, "[unknown]"),
            "num": _get_int(gift, 3, 1),
            "price": _get_int(gift, 5, 0),
            "coin_type": _get_text(gift, 8, ""),
            "action": _get_text(gift, 18, "投喂"),
        })

    return gifts

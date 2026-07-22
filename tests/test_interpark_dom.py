import interpark_dom


def test_selectors_present_and_nonempty():
    for name in [
        "SEAT_PAGE_MARKER", "SEAT_CIRCLE", "GOODS_DAYS", "GOODS_SIDE_TOGGLE",
        "GOODS_MONTH_CURRENT", "GOODS_MONTH_NEXT", "GOODS_TIME_LABEL",
        "GOODS_BOOK_BUTTON", "SCHEDULE_DATE_QUERY", "SESSION_TIMER_QUERY",
        "LAYER_DATE_BUTTON", "LAYER_CONTAINER", "LAYER_MONTH",
        "LAYER_SWIPER_ACTIVE", "LAYER_DATE_ITEM_BUTTON", "LAYER_DATE_NUMBER",
        "LAYER_TIME_BUTTON", "LAYER_APPLY_BUTTON", "LAYER_SWIPER_NEXT_ID",
        "LAYER_SWIPER_PREV_ID", "READ_SEATS_JS",
    ]:
        value = getattr(interpark_dom, name)
        assert isinstance(value, str) and value


def test_read_seats_js_targets_seat_circle():
    assert "circle.js-seat" in interpark_dom.READ_SEATS_JS

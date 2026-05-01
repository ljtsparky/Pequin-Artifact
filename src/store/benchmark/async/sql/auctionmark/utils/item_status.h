#ifndef AUCTIONMARK_ITEM_STATUS_H
#define AUCTIONMARK_ITEM_STATUS_H

#include <array>

namespace auctionmark {

enum class ItemStatus {
    OPEN = 0,
    ENDING_SOON, // Only used internally
    WAITING_FOR_PURCHASE,
    CLOSED,
    //NULL_VAL, //Special NULL handling
};

class ItemStatusHelper {
private:
    static const bool internal_statuses[4];

public:
    static bool is_internal(ItemStatus status) {
        return internal_statuses[static_cast<int>(status)];
    }

    static ItemStatus get(long idx) {
        return static_cast<ItemStatus>(idx);
    }
};

} // namespace auctionmark

#include <fmt/core.h>

template <>
struct fmt::formatter<auctionmark::ItemStatus> {
    constexpr auto parse(fmt::format_parse_context& ctx) { return ctx.begin(); }
    template <typename FormatContext>
    auto format(auctionmark::ItemStatus s, FormatContext& ctx) const {
        return fmt::format_to(ctx.out(), "{}", static_cast<int>(s));
    }
};

#endif // AUCTIONMARK_ITEM_STATUS_H
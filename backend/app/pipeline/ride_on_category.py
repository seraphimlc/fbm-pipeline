import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RideOnCategoryOption:
    key: str
    path_parts: tuple[str, ...]
    item_type_keyword: str
    markers: tuple[str, ...]

    @property
    def categories(self) -> list[str]:
        return [*self.path_parts[:-1], f"{self.path_parts[-1]} ({self.key})"]

    @property
    def leaf_category(self) -> str:
        return self.categories[-1]


RIDE_ON_CATEGORY_OPTIONS: tuple[RideOnCategoryOption, ...] = (
    RideOnCategoryOption(
        key="childrens-rocking-horses-and-animals",
        path_parts=("玩具和游戏", "婴幼玩具", "摇摆木马和动物"),
        item_type_keyword="玩具和游戏 > 婴幼玩具 > 摇摆木马和动物 (childrens-rocking-horses-and-animals)",
        markers=("rocking horse", "rocking animal", "rocker", "摇摆木马"),
    ),
    RideOnCategoryOption(
        key="childrens-push-ride-ons",
        path_parts=("玩具和游戏", "童车、助步、轮滑", "儿童推车"),
        item_type_keyword="玩具和游戏 > 童车、助步、轮滑 > 儿童推车 (childrens-push-ride-ons)",
        markers=("push ride", "push car", "push wagon", "walker", "儿童推车"),
    ),
    RideOnCategoryOption(
        key="childrens-tricycles",
        path_parts=("玩具和游戏", "童车、助步、轮滑", "三轮车"),
        item_type_keyword="玩具和游戏 > 童车、助步、轮滑 > 三轮车 (childrens-tricycles)",
        markers=("tricycle", "trike", "three wheel", "3 wheel", "三轮车"),
    ),
    RideOnCategoryOption(
        key="childrens-pedal-ride-ons",
        path_parts=("玩具和游戏", "童车、助步、轮滑", "儿童踏板车"),
        item_type_keyword="玩具和游戏 > 童车、助步、轮滑 > 儿童踏板车 (childrens-pedal-ride-ons)",
        markers=("pedal", "go kart", "go-kart", "踏板车"),
    ),
    RideOnCategoryOption(
        key="childrens-powered-ride-ons",
        path_parts=("玩具和游戏", "童车、助步、轮滑", "儿童电瓶车"),
        item_type_keyword="玩具和游戏 > 童车、助步、轮滑 > 儿童电瓶车 (childrens-powered-ride-ons)",
        markers=(
            "powered ride",
            "electric ride",
            "battery powered ride",
            "ride on car",
            "ride-on car",
            "electric car",
            "electric vehicle",
            "kids electric",
            "children electric",
            "atv",
            "utv",
            "jeep",
            "motorcycle",
            "12v powered",
            "12v ride",
            "24v powered",
            "24v ride",
            "6v powered",
            "6v ride",
            "儿童电瓶车",
        ),
    ),
)
DEFAULT_RIDE_ON_CATEGORY = next(
    option for option in RIDE_ON_CATEGORY_OPTIONS if option.key == "childrens-powered-ride-ons"
)

RIDE_ON_CATEGORY_MARKERS = tuple(
    dict.fromkeys(
        [
            "ride on",
            "ride-on",
            "kids ride",
            "children ride",
            "ride_on_toy",
            "powered ride",
            "children's powered ride",
            "kids' electric vehicles",
            "儿童电瓶车",
            *[option.key for option in RIDE_ON_CATEGORY_OPTIONS],
            *[marker for option in RIDE_ON_CATEGORY_OPTIONS for marker in option.markers],
        ]
    )
)


def is_ride_on_category_text(text: str) -> bool:
    normalized = (text or "").lower()
    return any(marker in normalized for marker in RIDE_ON_CATEGORY_MARKERS)


def select_ride_on_category(text: str) -> RideOnCategoryOption | None:
    normalized = (text or "").lower()
    for option in RIDE_ON_CATEGORY_OPTIONS:
        if any(marker in normalized for marker in option.markers):
            return option
    if is_ride_on_category_text(normalized):
        return DEFAULT_RIDE_ON_CATEGORY
    if re.search(r"\b(?:kids?|children'?s?)\b.*\b(?:car|vehicle|tractor|atv|utv)\b", normalized):
        return DEFAULT_RIDE_ON_CATEGORY
    return None

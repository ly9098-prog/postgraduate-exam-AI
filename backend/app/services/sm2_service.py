import math
from datetime import date, timedelta


def calc_sm2(
    quality: int,
    efactor: float = 2.5,
    interval: int = 0,
    repetitions: int = 0,
    review_date: date | None = None,
) -> dict:
    """SM-2 算法核心：根据质量评分计算下次复习参数。

    quality: 0-5
      5 = 完全正确，毫不犹豫
      4 = 正确，稍有犹豫
      3 = 正确，但较困难
      2 = 错误，但能想起来正确答案
      1 = 错误，想起来正确答案但很困难
      0 = 完全错误，毫无印象

    返回: {efactor, interval, repetitions, next_review_date}
    """
    if quality < 0 or quality > 5:
        raise ValueError(f"质量评分必须在 0-5 之间，收到: {quality}")

    if quality < 3:
        new_repetitions = 0
        new_interval = 1
    else:
        if repetitions == 0:
            new_interval = 1
        elif repetitions == 1:
            new_interval = 6
        else:
            new_interval = max(1, int(math.floor(interval * efactor + 0.5)))
        new_repetitions = repetitions + 1

    new_efactor = efactor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_efactor = max(1.3, new_efactor)

    today = review_date or date.today()
    next_review_date = today + timedelta(days=new_interval)

    return {
        "efactor": round(new_efactor, 4),
        "interval": new_interval,
        "repetitions": new_repetitions,
        "next_review_date": next_review_date,
    }

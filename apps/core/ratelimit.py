from django.core.cache import cache


def hit(key, limit, window_seconds):
    """عدّاد بنافذة زمنية ثابتة. يعيد True إذا تم تجاوز الحد."""
    cache.add(key, 0, window_seconds)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window_seconds)
        count = 1
    return count > limit


def reset(key):
    cache.delete(key)

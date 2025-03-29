from pydantic_yaml import parse_yaml_file_as

from .config import DEFAULT_ID, ScheduleObject
from .timer import DAY, HOUR, MINUTE, EtaSeconds, EventRing, GlobalOffsetRing


def eta_to_str(eta: EtaSeconds):
    d = eta // DAY
    od = d * DAY
    h = (eta - od) // HOUR
    oh = h * HOUR
    m = (eta - od - oh) // MINUTE

    return f"{d}D {h}:{str(m).rjust(2, '0')}:{str(eta % MINUTE).rjust(2, '0')}"


def display(eta: EtaSeconds, glr: GlobalOffsetRing, index: int):
    now_subject = glr[index].subject
    teacher = (
        ""
        if now_subject.teacher is None or now_subject.teacher == ""
        else now_subject.teacher + " - "
    )
    room = (
        " - " + now_subject.room
        if now_subject.room is None and now_subject.room == ""
        else ""
    )
    precent = (glr[index].time_offset - eta) / (
        glr[index].time_offset - (0 if index == 0 else glr[index - 1].time_offset)
    )
    prev = (
        ""
        if index == 0
        else " ".join(
            list(
                it.subject.short_name
                if it.subject.short_name is not None and it.subject.short_name != ""
                else (
                    it.subject.name[0]
                    if it.subject.name is not None and it.subject.name != ""
                    else "空"
                )
                for it in (it for it in glr[:index] if it.subject_id != DEFAULT_ID)
            )[:-5:-1]
        )
    )
    now = f"| {teacher}{now_subject.name}{room} ETA: {eta_to_str(eta)}({precent:.2f}%)|"
    post = (
        ""
        if index == len(glr)
        else " ".join(
            it.subject.short_name
            if it.subject.short_name is not None and it.subject.short_name != ""
            else (
                it.subject.name[0]
                if it.subject.name is not None and it.subject.name != ""
                else "空"
            )
            for index, it in enumerate(
                it for it in glr[index + 1 :] if it.subject_id != DEFAULT_ID
            )
            if index < 4
        )
    )
    print(prev, now, post)
    # print(*list(f"{eta_to_str(it.time_offset)} {it}" for it in glr),sep='\t\n')
    pass


def main():
    (
        EventRing.from_object(
            parse_yaml_file_as(ScheduleObject, "./schedule.full-example.yaml")
        )
        .to_timer()
        .exec(display)
    )


if __name__ == "__main__":
    main()

"""Which catalog exercise (by `source_id`) shows the how-to steps for each exercise the plans generator uses.

The weekly plan (plans/generator.py) names its exercises in plain text. These links, picked by hand, point each
name at the same movement in the catalog. A name maps to `None` when the catalog has no close enough match (for
example a banded variation it doesn't list); that exercise is still logged, just without steps.

`test_catalog.ExerciseLinkTests` fails when the generator gains a name that isn't listed here, or when a link points
at an id that isn't in the catalog, so the two can't drift apart unnoticed.
"""

CATALOG_IDS: dict[str, str | None] = {
    # Squat
    'Barbell Back Squat': '0043',  # barbell full squat
    'Leg Press': '0739',  # sled 45° leg press
    'Goblet Squat': '1760',  # dumbbell goblet squat
    'Banded Squat': '1004',  # band squat
    'Bodyweight Squat': None,
    # Hinge
    'Romanian Deadlift': '0085',  # barbell romanian deadlift
    'Dumbbell Romanian Deadlift': '1459',
    'Banded Good Morning': None,
    'Glute Bridge': '3013',  # low glute bridge on floor
    # Push
    'Barbell Bench Press': '0025',
    'Machine Chest Press': '0577',  # lever chest press
    'Dumbbell Bench Press': '0289',
    'Banded Chest Press': '1254',  # band bench press
    'Push-Up': '0662',
    # Overhead
    'Barbell Overhead Press': None,
    'Machine Shoulder Press': '0603',  # lever shoulder press
    'Dumbbell Shoulder Press': '0405',  # dumbbell seated shoulder press
    'Banded Overhead Press': '0997',  # band shoulder press
    'Pike Push-Up': None,
    # Row
    'Barbell Bent-Over Row': '0027',
    'Seated Cable Row': '0861',  # cable seated row
    'One-Arm Dumbbell Row': None,
    'Banded Row': '3144',  # resistance band seated straight back row
    'Prone Y-T Raise': None,
    # Pulldown
    'Lat Pulldown': '0150',  # cable bar lateral pulldown
    'Banded Lat Pulldown': '0974',  # band close-grip pulldown
    'Dumbbell Pullover': '0375',
    'Superman Hold': None,
    # Lunge
    'Dumbbell Walking Lunge': '0336',  # dumbbell lunge
    'Barbell Reverse Lunge': '0078',  # barbell rear lunge
    'Banded Split Squat': '1001',  # band single leg split squat
    'Reverse Lunge': None,
    # Triceps
    'Close-Grip Bench Press': '0030',  # barbell close-grip bench press
    'Cable Triceps Pressdown': '0201',  # cable pushdown
    'Dumbbell Overhead Triceps Extension': None,
    'Banded Triceps Pressdown': None,
    'Diamond Push-Up': '0283',
    # Biceps
    'Barbell Curl': '0031',
    'Cable Biceps Curl': '0868',  # cable curl
    'Dumbbell Curl': '0294',  # dumbbell biceps curl
    'Banded Curl': '0968',  # band alternating biceps curl
    'Towel Isometric Curl': None,
    # Core and cardio
    'Plank': None,
    'Treadmill or Bike Intervals': None,
    'Brisk Walk or Jog': None,
}


def catalog_id_for(name: str) -> str | None:
    return CATALOG_IDS.get(name)

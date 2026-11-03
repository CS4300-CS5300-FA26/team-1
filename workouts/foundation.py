"""The exercises the planner chooses from, picked by hand from the catalog (ADR-009).

The upstream dataset has 1,324 exercises and no difficulty rating, and its `target` labels are loose (stretches and
"flutter kicks" are filed under glutes). Choosing from it by label would put odd or advanced moves in a beginner's
week, so the planner only uses these standard movements, each named by the catalog's `source_id`. The whole catalog
is still loaded, because every exercise can be logged and shown.

Each slot is a movement the plan wants in a session. Under it, each equipment class lists exercises in order of
preference: the first is the most standard version, and the planner rotates through the list week to week.
`tests` check that every id exists, is active, and belongs to the class it is listed under (cardio excepted: a
treadmill walk is filed under machines in the dataset but is cardio equipment to the user).
"""

SQUAT = 'squat'
HINGE = 'hinge'
PUSH_HORIZONTAL = 'push_horizontal'
PUSH_VERTICAL = 'push_vertical'
PULL_HORIZONTAL = 'pull_horizontal'
PULL_VERTICAL = 'pull_vertical'
BICEPS = 'biceps'
TRICEPS = 'triceps'
CORE = 'core'
CALVES = 'calves'
CARDIO = 'cardio'

SLOT_LABELS = {
    SQUAT: 'Squat or lunge',
    HINGE: 'Hip hinge',
    PUSH_HORIZONTAL: 'Chest push',
    PUSH_VERTICAL: 'Shoulder press',
    PULL_HORIZONTAL: 'Row',
    PULL_VERTICAL: 'Pulldown or pull-up',
    BICEPS: 'Biceps',
    TRICEPS: 'Triceps',
    CORE: 'Core',
    CALVES: 'Calves',
    CARDIO: 'Cardio',
}

# Big, multi-joint lifts get lower reps and more rest; the rest are accessory work.
COMPOUND_SLOTS = frozenset({SQUAT, HINGE, PUSH_HORIZONTAL, PUSH_VERTICAL, PULL_HORIZONTAL, PULL_VERTICAL})

# slot -> equipment class -> catalog source_ids, most standard first. A slot with nothing for a user's equipment is
# left out of their plan (for example a pulldown with bodyweight only) rather than filled with a poor substitute.
POOLS: dict[str, dict[str, tuple[str, ...]]] = {
    SQUAT: {
        'none': ('2368', '1460', '3769', '1685'),
        'dumbbells': ('1760', '0413', '0336', '0381', '0431'),
        'barbell': ('0043', '0042', '1436'),
        'machines': ('0739', '0770', '0760', '0585'),
        'bands': ('1004', '1008'),
    },
    HINGE: {
        'none': ('3013', '3561', '0489'),
        'dumbbells': ('1459', '0300', '0432'),
        'barbell': ('0085', '0032', '1409'),
        'machines': ('0586', '0599', '0196', '0573', '0157'),
        'bands': ('0991', '1010'),
    },
    PUSH_HORIZONTAL: {
        'none': ('0662', '0493', '0279'),
        'dumbbells': ('0289', '0314', '0352', '0308'),
        'barbell': ('0025', '0047'),
        'machines': ('0577', '1299', '0748', '0227'),
        'bands': ('1254',),
    },
    PUSH_VERTICAL: {
        'dumbbells': ('0426', '2137', '0334'),
        'barbell': ('1456', '1457'),
        'machines': ('0603', '0587', '0219', '0584', '0178'),
        'bands': ('0997', '0977', '1017'),
    },
    PULL_HORIZONTAL: {
        'none': ('0499', '2298'),
        'dumbbells': ('0293', '0327'),
        'barbell': ('0027', '3017'),
        'machines': ('0180', '0606', '0581', '1324', '0234'),
        'bands': ('3144', '1022'),
    },
    PULL_VERTICAL: {
        'machines': ('0150', '0198', '0017', '0579'),
        'bands': ('1013', '0974', '0970'),
    },
    BICEPS: {
        'dumbbells': ('0294', '0313', '0285'),
        'barbell': ('0031', '0023'),
        'machines': ('0868', '0165', '0195'),
        'bands': ('0968', '0976'),
    },
    TRICEPS: {
        'none': ('0129', '0259', '0283', '0672'),
        'dumbbells': ('0333', '0351', '0296'),
        'barbell': ('0030', '0061'),
        'machines': ('0201', '0200', '0194'),
        'bands': ('0998',),
    },
    CORE: {
        'none': ('0274', '0276', '0872', '0687', '0006', '0267'),
        'machines': ('0212', '0226', '0873', '0223'),
        'bands': ('0972', '1005', '1002'),
    },
    CALVES: {
        'none': ('1373',),
        'dumbbells': ('0417', '1379'),
        'barbell': ('1372',),
        'machines': ('1375', '0594', '2335'),
    },
    CARDIO: {
        'none': ('0685', '0630', '3361', '3672', '1160'),
        'cardio': ('2141', '2311', '2138', '2142', '3666'),
    },
}

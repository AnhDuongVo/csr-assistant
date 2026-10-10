from csr_assistant.numcheck import contextual_unverified, unverified


def test_both_directions_and_explicit_sign():
    assert unverified("HbA1c increased by 1.2%", ["Change: -1.2"])
    assert unverified("HbA1c decreased by 1.2%", ["Change: 1.2"])
    assert unverified("Change -1.2%", ["Change: 1.2"])
    assert not unverified("HbA1c decreased by 1.2%", ["Change: -1.2"])


def test_correct_number_wrong_arm():
    source = "Endpoint: nausea | SYN-301 n: 22 | SYN-301 %: 18.5 | placebo n: 6 | placebo %: 5.0"
    assert contextual_unverified("Nausea occurred in 6 patients with SYN-301.", [source])
    assert not contextual_unverified("Nausea occurred in 22 patients with SYN-301.", [source])


def test_wrong_endpoint_does_not_supply_number():
    from csr_assistant.reviewer import candidate_rows
    from csr_assistant.sources import SourcePackage, Table

    pkg = SourcePackage(
        "",
        [],
        [
            Table(
                "T1",
                "ae",
                "Adverse events",
                "adverse_events",
                ["Endpoint", "SYN-301 n"],
                [["Nausea", "22"], ["Headache", "6"]],
            )
        ],
    )
    rows = candidate_rows(pkg, "Nausea occurred in 6 patients.")
    assert rows == ["T1.R1"]
    assert unverified("Nausea occurred in 6 patients.", [pkg.rows[r] for r in rows])


async def test_generated_number_from_wrong_endpoint_is_flagged():
    from csr_assistant.reviewer import review
    from csr_assistant.schemas import DraftSection, DraftSentence
    from csr_assistant.sources import SourcePackage, Table

    pkg = SourcePackage(
        "",
        [],
        [
            Table(
                "T1",
                "ae",
                "Adverse events",
                "adverse_events",
                ["Endpoint", "SYN-301 n"],
                [["Nausea", "22"], ["Headache", "22"]],
            )
        ],
    )
    drafted = [
        DraftSection(
            number="12.2.1",
            title="AE",
            status="drafted",
            sentences=[DraftSentence(text="Nausea occurred in 22 patients.", citations=["T1.R2"])],
        )
    ]
    findings = await review(pkg, drafted, None)
    assert any("endpoint" in f.detail for f in findings)


def test_conflicting_values_across_sections_keep_time_context():
    from csr_assistant.reviewer import conflicting_claims

    claims = [
        ("11.1", "At week 26, HbA1c change was -1.2% with SYN-301.", "draft"),
        ("13.1", "At week 26, HbA1c change was -0.3% with SYN-301.", "draft"),
    ]
    assert len(conflicting_claims(claims)) == 1
    claims[1] = ("13.1", "At week 12, HbA1c change was -0.3% with SYN-301.", "draft")
    assert conflicting_claims(claims) == []

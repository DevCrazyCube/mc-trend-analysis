"""Unit tests for X entity extraction, normalization, and noise rejection.

Covers:
- Cashtag, hashtag, mention, quoted name, proper noun extraction
- Canonicalization and variant tracking
- Chronic term rejection
- Similarity-based merging
- Noise rejection (min mentions, min authors)
- Batch extraction from tweet events
"""
from __future__ import annotations

import pytest

from mctrend.narrative.entity_extraction import (
    CandidateEntity,
    XEntityExtractor,
    canonicalize,
    trigram_jaccard,
    DEFAULT_CHRONIC_TERMS,
)


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


class TestCanonicalize:
    def test_strips_dollar_sign(self):
        assert canonicalize("$TRUMP") == "TRUMP"

    def test_strips_hash(self):
        assert canonicalize("#solana") == "SOLANA"

    def test_strips_at_sign(self):
        assert canonicalize("@elonmusk") == "ELONMUSK"

    def test_uppercases(self):
        assert canonicalize("Trump") == "TRUMP"

    def test_strips_whitespace(self):
        assert canonicalize("  Trump  ") == "TRUMP"

    def test_multiple_leading_symbols(self):
        assert canonicalize("$#TOKEN") == "TOKEN"

    def test_empty_string(self):
        assert canonicalize("") == ""


# ---------------------------------------------------------------------------
# Trigram Jaccard similarity
# ---------------------------------------------------------------------------


class TestTrigramJaccard:
    def test_identical_strings(self):
        assert trigram_jaccard("TRUMP", "TRUMP") == 1.0

    def test_completely_different(self):
        assert trigram_jaccard("ABCDEF", "XYZWVU") == 0.0

    def test_similar_strings(self):
        sim = trigram_jaccard("TRUMP", "TRUMPS")
        assert sim > 0.5

    def test_short_strings(self):
        sim = trigram_jaccard("AB", "AB")
        assert sim == 1.0

    def test_empty_strings(self):
        assert trigram_jaccard("", "") == 0.0


# ---------------------------------------------------------------------------
# Single-tweet extraction
# ---------------------------------------------------------------------------


class TestExtractFromTweet:
    def setup_method(self):
        self.extractor = XEntityExtractor()

    def test_cashtag_extracted(self):
        entities = self.extractor.extract_from_tweet("Buy $TRUMP now!")
        canonicals = [e[1] for e in entities]
        assert "TRUMP" in canonicals

    def test_multiple_cashtags(self):
        entities = self.extractor.extract_from_tweet("$SOL vs $PEPE battle")
        canonicals = [e[1] for e in entities]
        assert "SOL" in canonicals
        assert "PEPE" in canonicals

    def test_hashtag_extracted(self):
        entities = self.extractor.extract_from_tweet("Trending #TrumpArrest today")
        canonicals = [e[1] for e in entities]
        assert "TRUMPARREST" in canonicals

    def test_quoted_name_extracted(self):
        entities = self.extractor.extract_from_tweet('They call it "Operation Warp Speed" and it works')
        canonicals = [e[1] for e in entities]
        assert "OPERATION WARP SPEED" in canonicals

    def test_proper_noun_extracted(self):
        entities = self.extractor.extract_from_tweet("something about Donald Trump is trending hard")
        canonicals = [e[1] for e in entities]
        assert "DONALD TRUMP" in canonicals

    def test_chronic_terms_rejected(self):
        entities = self.extractor.extract_from_tweet("$BTC and $ETH are pumping")
        canonicals = [e[1] for e in entities]
        assert "BTC" not in canonicals
        assert "ETH" not in canonicals

    def test_short_terms_rejected(self):
        entities = self.extractor.extract_from_tweet("$X is hot")
        canonicals = [e[1] for e in entities]
        # $X -> "X" which is only 1 char, below min_entity_length=2
        assert "X" not in canonicals

    def test_deduplication_within_tweet(self):
        entities = self.extractor.extract_from_tweet("$TRUMP $TRUMP $TRUMP")
        canonicals = [e[1] for e in entities]
        assert canonicals.count("TRUMP") == 1

    def test_entity_type_cashtag(self):
        entities = self.extractor.extract_from_tweet("$MOONDOG launch")
        types = {e[1]: e[2] for e in entities}
        assert types.get("MOONDOG") == "cashtag"

    def test_entity_type_hashtag(self):
        entities = self.extractor.extract_from_tweet("#memecoin is trending now")
        types = {e[1]: e[2] for e in entities}
        assert types.get("MEMECOIN") == "hashtag"

    def test_entity_type_proper_noun(self):
        entities = self.extractor.extract_from_tweet("something about Elon Musk said today")
        types = {e[1]: e[2] for e in entities}
        assert types.get("ELON MUSK") == "person"

    def test_max_entities_per_tweet_capped(self):
        # Build a tweet with many cashtags
        tags = " ".join(f"${chr(65+i)}{chr(65+i)}" for i in range(20))
        entities = self.extractor.extract_from_tweet(tags)
        assert len(entities) <= 10

    def test_url_not_extracted_as_entity(self):
        entities = self.extractor.extract_from_tweet("Check https://example.com/big-news for details")
        canonicals = [e[1] for e in entities]
        for c in canonicals:
            assert "HTTPS" not in c
            assert "EXAMPLE" not in c


# ---------------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------------


class TestExtractFromTweets:
    def setup_method(self):
        self.extractor = XEntityExtractor()

    def _make_event(self, text, author="@user1", engagement=0.5):
        return {
            "raw_text": text,
            "source_name": author,
            "_engagement_score": engagement,
        }

    def test_aggregates_across_tweets(self):
        tweets = [
            self._make_event("$TRUMP coin launched", "@user1"),
            self._make_event("$TRUMP is pumping", "@user2"),
            self._make_event("$TRUMP going viral", "@user3"),
        ]
        candidates = self.extractor.extract_from_tweets(tweets)
        assert "TRUMP" in candidates
        assert candidates["TRUMP"].mention_count == 3
        assert candidates["TRUMP"].unique_authors == 3

    def test_engagement_accumulated(self):
        tweets = [
            self._make_event("$PEPE launch", "@a", 0.3),
            self._make_event("$PEPE moon", "@b", 0.7),
        ]
        candidates = self.extractor.extract_from_tweets(tweets)
        assert abs(candidates["PEPE"].engagement_total - 1.0) < 0.01

    def test_variants_tracked(self):
        tweets = [
            self._make_event("$Trump launch", "@a"),
            self._make_event("$TRUMP coin", "@b"),
        ]
        candidates = self.extractor.extract_from_tweets(tweets)
        assert "TRUMP" in candidates
        assert len(candidates["TRUMP"].variants) >= 1

    def test_sample_texts_capped(self):
        tweets = [
            self._make_event(f"$DOGE mention {i}", f"@u{i}")
            for i in range(10)
        ]
        candidates = self.extractor.extract_from_tweets(tweets)
        assert len(candidates["DOGE"].sample_texts) <= 5


# ---------------------------------------------------------------------------
# Similarity merge
# ---------------------------------------------------------------------------


class TestMergeSimilar:
    def setup_method(self):
        self.extractor = XEntityExtractor(merge_similarity_threshold=0.7)

    def test_similar_entities_merged(self):
        candidates = {
            "TRUMP": CandidateEntity("TRUMP"),
            "TRUMPS": CandidateEntity("TRUMPS"),
        }
        candidates["TRUMP"].mention_count = 5
        candidates["TRUMPS"].mention_count = 2
        merged = self.extractor.merge_similar(candidates)
        assert "TRUMP" in merged
        assert "TRUMPS" not in merged
        assert merged["TRUMP"].mention_count == 7

    def test_dissimilar_entities_not_merged(self):
        candidates = {
            "TRUMP": CandidateEntity("TRUMP"),
            "BIDEN": CandidateEntity("BIDEN"),
        }
        candidates["TRUMP"].mention_count = 3
        candidates["BIDEN"].mention_count = 3
        merged = self.extractor.merge_similar(candidates)
        assert "TRUMP" in merged
        assert "BIDEN" in merged

    def test_smaller_absorbed_into_larger(self):
        candidates = {
            "TRUMPCOIN": CandidateEntity("TRUMPCOIN"),
            "TRUMPCOINS": CandidateEntity("TRUMPCOINS"),
        }
        candidates["TRUMPCOIN"].mention_count = 1
        candidates["TRUMPCOINS"].mention_count = 10
        merged = self.extractor.merge_similar(candidates)
        # TRUMPCOINS has more mentions, so it should be the winner
        assert "TRUMPCOINS" in merged
        assert merged["TRUMPCOINS"].mention_count == 11


# ---------------------------------------------------------------------------
# Noise rejection
# ---------------------------------------------------------------------------


class TestNoiseRejection:
    def setup_method(self):
        self.extractor = XEntityExtractor()

    def test_below_min_mentions_rejected(self):
        candidates = {"RARE": CandidateEntity("RARE")}
        candidates["RARE"].mention_count = 1
        kept = self.extractor.reject_noise(candidates, min_mentions=3)
        assert "RARE" not in kept

    def test_meets_min_mentions_kept(self):
        candidates = {"POPULAR": CandidateEntity("POPULAR")}
        candidates["POPULAR"].mention_count = 5
        candidates["POPULAR"].author_ids = {"a", "b", "c"}
        kept = self.extractor.reject_noise(candidates, min_mentions=3, min_authors=1)
        assert "POPULAR" in kept

    def test_below_min_authors_rejected(self):
        candidates = {"BOT": CandidateEntity("BOT")}
        candidates["BOT"].mention_count = 10
        candidates["BOT"].author_ids = {"single_bot"}
        kept = self.extractor.reject_noise(candidates, min_mentions=1, min_authors=3)
        assert "BOT" not in kept

    def test_chronic_term_rejected_after_merge(self):
        # Even if it passed initial extraction, reject chronic in noise filter
        candidates = {"BTC": CandidateEntity("BTC")}
        candidates["BTC"].mention_count = 100
        candidates["BTC"].author_ids = set(f"u{i}" for i in range(50))
        kept = self.extractor.reject_noise(candidates)
        assert "BTC" not in kept

    def test_too_short_rejected(self):
        candidates = {"A": CandidateEntity("A")}
        candidates["A"].mention_count = 50
        kept = self.extractor.reject_noise(candidates)
        assert "A" not in kept


# ---------------------------------------------------------------------------
# CandidateEntity
# ---------------------------------------------------------------------------


class TestCandidateEntity:
    def test_to_dict_structure(self):
        c = CandidateEntity("TRUMP", entity_type="person")
        c.add_mention("Trump", "user1", 0.5, "Trump is trending")
        c.add_mention("$TRUMP", "user2", 0.8, "$TRUMP launched")
        d = c.to_dict()
        assert d["canonical"] == "TRUMP"
        assert d["entity_type"] == "person"
        assert d["mention_count"] == 2
        assert d["unique_authors"] == 2
        assert d["engagement_total"] == 1.3
        assert "first_seen" in d

    def test_unique_authors_property(self):
        c = CandidateEntity("TEST")
        c.add_mention("test", "a")
        c.add_mention("test", "a")  # same author
        c.add_mention("test", "b")
        assert c.unique_authors == 2


# ---------------------------------------------------------------------------
# Default chronic terms
# ---------------------------------------------------------------------------


class TestDefaultChronicTerms:
    def test_common_crypto_terms_are_chronic(self):
        for term in ["BITCOIN", "BTC", "ETHEREUM", "ETH", "CRYPTO", "NFT", "DEFI"]:
            assert term in DEFAULT_CHRONIC_TERMS

    def test_social_noise_is_chronic(self):
        for term in ["GM", "GN", "WAGMI", "LFG", "DYOR"]:
            assert term in DEFAULT_CHRONIC_TERMS

    def test_specific_entities_not_chronic(self):
        for term in ["TRUMP", "ELON", "DOGE", "PEPE", "MOONDOG"]:
            assert term not in DEFAULT_CHRONIC_TERMS

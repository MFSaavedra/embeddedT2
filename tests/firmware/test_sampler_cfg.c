/**
 * @file test_sampler_cfg.c
 * @brief Host-side test of esp32_firmware/main/sampler_cfg.c, the CFG parser and formatter
 *        (TODO.md UT3; spec 5: invalid commands are rejected and change nothing).
 *
 * Fields are split with proto_split(), exactly as commands.c does before calling
 * sampler_cfg_parse(). The accepted strings are the ones tests/test_messages.py expects the
 * GUI to build, which keeps the two sides of the CFG command in step.
 * Built and run by tests/test_firmware_host.py.
 */
#include "protocol.h"
#include "sampler_cfg.h"

#include <stdio.h>
#include <string.h>

/** Number of failed CHECK()s. */
static int s_failures;

/** Record a failure with its location instead of aborting, so one run reports every problem. */
#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);           \
            s_failures++;                                                    \
        }                                                                    \
    } while (0)

/** A configuration no parse can produce, to prove a failed parse wrote nothing. */
static const sampler_cfg_t SENTINEL = { 1234, 0x80, true, 99, true, 999 };

/**
 * @brief Split @p text (the fields after "CFG,") like commands.c does, and parse it.
 * @param      text     Comma-separated key=value fields.
 * @param[out] out      Parsed configuration (preset to SENTINEL).
 * @param[out] bad_key  Offending key on failure, else NULL.
 * @return What sampler_cfg_parse() returned.
 */
static bool parse(const char *text, sampler_cfg_t *out, const char **bad_key)
{
    char buf[256];
    char *fields[12];
    snprintf(buf, sizeof buf, "%s", text);
    int n = proto_split(buf, fields, 12);
    *out = SENTINEL;
    *bad_key = NULL;
    return sampler_cfg_parse(fields, n, out, bad_key);
}

/**
 * @brief Expect @p text to be rejected, blaming @p key, with nothing written.
 * @param text  Fields to parse.
 * @param key   Key the error must name.
 * @return true if all of that holds.
 */
static bool rejects(const char *text, const char *key)
{
    sampler_cfg_t cfg;
    const char *bad;
    bool ok = !parse(text, &cfg, &bad) && bad != NULL && strcmp(bad, key) == 0 &&
              memcmp(&cfg, &SENTINEL, sizeof cfg) == 0;
    if (!ok) {
        printf("  not rejected as %s: %s (blamed %s)\n", key, text, bad ? bad : "nothing");
    }
    return ok;
}

/**
 * @brief Expect @p text to parse and to format back to exactly @p echo.
 * @param text  Fields to parse.
 * @param echo  Expected sampler_cfg_format() output.
 * @return true if both hold.
 */
static bool round_trip(const char *text, const char *echo)
{
    sampler_cfg_t cfg;
    const char *bad;
    char out[160];
    if (!parse(text, &cfg, &bad) || !sampler_cfg_valid(&cfg)) {
        printf("  rejected: %s (blamed %s)\n", text, bad ? bad : "nothing");
        return false;
    }
    sampler_cfg_format(&cfg, out, sizeof out);
    if (strcmp(out, echo) != 0) {
        printf("  %s\n  formatted as %s\n  expected     %s\n", text, out, echo);
        return false;
    }
    return true;
}

/** Valid fields with one of them replaced, for the per-field rejection tests. */
#define CFG_WITH(rate, vars, avg, win, peak, thr)                                       \
    "sampling_hz=" rate ",variables=" vars ",avg_enabled=" avg ",window_s=" win          \
    ",peak_enabled=" peak ",threshold_c=" thr

/** @brief Run every check; exit status 0 only if all passed. */
int main(void)
{
    char text[160];
    sampler_cfg_t cfg;
    const char *bad;

    /* Defaults: valid, and formatted as the GUI's Config().payload() minus "CFG,". */
    const sampler_cfg_t def = sampler_cfg_default();
    CHECK(sampler_cfg_valid(&def));
    sampler_cfg_format(&def, text, sizeof text);
    CHECK(strcmp(text, CFG_WITH("1", "THP", "0", "10", "0", "28.0")) == 0);

    /* The README / spec example, and a round trip of every rate, window and edge threshold. */
    CHECK(round_trip(CFG_WITH("2", "TP", "1", "10", "1", "28.0"),
                     CFG_WITH("2", "TP", "1", "10", "1", "28.0")));
    CHECK(parse(CFG_WITH("2", "TP", "1", "10", "1", "28.0"), &cfg, &bad) &&
          cfg.period_ms == 500 && cfg.vars == (SAMPLER_VAR_T | SAMPLER_VAR_P) &&
          cfg.avg_enabled && cfg.avg_window_s == 10 && cfg.peak_enabled &&
          cfg.threshold_dc == 280);
    CHECK(round_trip(CFG_WITH("0.5", "H", "0", "5", "0", "-40.0"),
                     CFG_WITH("0.5", "H", "0", "5", "0", "-40.0")));
    CHECK(round_trip(CFG_WITH("5", "HP", "1", "60", "1", "85.0"),
                     CFG_WITH("5", "HP", "1", "60", "1", "85.0")));
    CHECK(round_trip(CFG_WITH("1", "T", "1", "30", "0", "-0.5"),
                     CFG_WITH("1", "T", "1", "30", "0", "-0.5")));
    CHECK(parse(CFG_WITH("1", "T", "1", "30", "0", "-0.5"), &cfg, &bad) &&
          cfg.threshold_dc == -5);
    /* The seven combinations; letters in any order, echoed in T, H, P order. */
    const char *combos[][2] = { { "T", "T" }, { "H", "H" }, { "P", "P" }, { "TH", "TH" },
                                { "PT", "TP" }, { "PH", "HP" }, { "PHT", "THP" } };
    for (int i = 0; i < 7; i++) {
        char in[160], echo[160];
        snprintf(in, sizeof in, "sampling_hz=1,variables=%s,avg_enabled=0,window_s=10,"
                 "peak_enabled=0,threshold_c=28.0", combos[i][0]);
        snprintf(echo, sizeof echo, "sampling_hz=1,variables=%s,avg_enabled=0,window_s=10,"
                 "peak_enabled=0,threshold_c=28.0", combos[i][1]);
        CHECK(round_trip(in, echo));
    }

    /* Wrong number of fields, missing, misspelt or reordered keys. */
    CHECK(rejects("sampling_hz=1,variables=T,avg_enabled=0,window_s=10,peak_enabled=0", "fields"));
    CHECK(rejects(CFG_WITH("1", "T", "0", "10", "0", "28.0") ",extra=1", "fields"));
    CHECK(rejects("variables=T,sampling_hz=1,avg_enabled=0,window_s=10,peak_enabled=0,"
                  "threshold_c=28.0", "sampling_hz"));
    CHECK(rejects("sampling_hz=1,vars=T,avg_enabled=0,window_s=10,peak_enabled=0,"
                  "threshold_c=28.0", "variables"));
    CHECK(rejects("sampling_hz=1,variables=T,avg_enabled=0,window_s=10,peak_enabled=0,"
                  "threshold_c", "threshold_c"));
    CHECK(rejects("sampling_hz=1,sampling_hz=1,avg_enabled=0,window_s=10,peak_enabled=0,"
                  "threshold_c=28.0", "variables"));

    /* Each field with a value outside its allowed set. */
    const char *bad_rates[] = { "3", "0", "1.0", "0.50", "", "5Hz", "-1" };
    for (size_t i = 0; i < sizeof bad_rates / sizeof bad_rates[0]; i++) {
        snprintf(text, sizeof text, "sampling_hz=%s,variables=T,avg_enabled=0,window_s=10,"
                 "peak_enabled=0,threshold_c=28.0", bad_rates[i]);
        CHECK(rejects(text, "sampling_hz"));
    }
    const char *bad_vars[] = { "", "TT", "THPT", "X", "t", "T,H" };
    for (size_t i = 0; i < sizeof bad_vars / sizeof bad_vars[0]; i++) {
        snprintf(text, sizeof text, "sampling_hz=1,variables=%s,avg_enabled=0,window_s=10,"
                 "peak_enabled=0,threshold_c=28.0", bad_vars[i]);
        /* "T,H" splits into an extra field: a field-count error, still a rejection */
        CHECK(rejects(text, strcmp(bad_vars[i], "T,H") == 0 ? "fields" : "variables"));
    }
    CHECK(rejects(CFG_WITH("1", "T", "2", "10", "0", "28.0"), "avg_enabled"));
    CHECK(rejects(CFG_WITH("1", "T", "", "10", "0", "28.0"), "avg_enabled"));
    CHECK(rejects(CFG_WITH("1", "T", "true", "10", "0", "28.0"), "avg_enabled"));
    const char *bad_windows[] = { "7", "0", "", "10s", "-5", "100", "1000", "6O" };
    for (size_t i = 0; i < sizeof bad_windows / sizeof bad_windows[0]; i++) {
        snprintf(text, sizeof text, "sampling_hz=1,variables=T,avg_enabled=0,window_s=%s,"
                 "peak_enabled=0,threshold_c=28.0", bad_windows[i]);
        CHECK(rejects(text, "window_s"));
    }
    CHECK(rejects(CFG_WITH("1", "T", "0", "10", "01", "28.0"), "peak_enabled"));
    const char *bad_thresholds[] = { "28", "28.05", "+28.0", "28.0C", "-40.1", "85.1", ".5",
                                     "-.5", "", "28.", "1000.0", "--1.0", "2 8.0" };
    for (size_t i = 0; i < sizeof bad_thresholds / sizeof bad_thresholds[0]; i++) {
        snprintf(text, sizeof text, "sampling_hz=1,variables=T,avg_enabled=0,window_s=10,"
                 "peak_enabled=0,threshold_c=%s", bad_thresholds[i]);
        CHECK(rejects(text, "threshold_c"));
    }

    /* The first invalid field is the one named, even when several are wrong. */
    CHECK(rejects(CFG_WITH("1", "", "0", "7", "0", "99.0"), "variables"));

    /* sampler_cfg_valid() guards sampler_set_config() against hand-built structs. */
    sampler_cfg_t c = def;
    c.period_ms = 300;
    CHECK(!sampler_cfg_valid(&c));
    c = def;
    c.vars = 0;
    CHECK(!sampler_cfg_valid(&c));
    c.vars = 0x08;
    CHECK(!sampler_cfg_valid(&c));
    c = def;
    c.avg_window_s = 7;
    CHECK(!sampler_cfg_valid(&c));
    c = def;
    c.threshold_dc = 851;
    CHECK(!sampler_cfg_valid(&c));
    CHECK(!sampler_cfg_valid(NULL));

    if (s_failures == 0) {
        printf("test_sampler_cfg: all checks passed\n");
    }
    return s_failures == 0 ? 0 : 1;
}

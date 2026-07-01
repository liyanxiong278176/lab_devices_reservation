package com.lab.reservation.common.result;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class ResultTest {
    @Test
    void ok_sets_success_code_and_data() {
        Result<String> r = Result.ok("hi");
        assertEquals(200, r.getCode());
        assertEquals("hi", r.getData());
    }

    @Test
    void fail_sets_error_code() {
        assertEquals(409, Result.fail(ResultCode.RESERVATION_CONFLICT).getCode());
    }
}

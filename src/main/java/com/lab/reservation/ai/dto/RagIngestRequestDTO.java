package com.lab.reservation.ai.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import lombok.Data;

@Data
public class RagIngestRequestDTO {

    @NotBlank(message = "doc_id 不能为空")
    @JsonAlias("doc_id")
    private String docId;

    @NotBlank(message = "text 不能为空")
    private String text;

    @NotNull(message = "device_id 不能为空")
    @Positive(message = "device_id 必须 > 0")
    @JsonAlias("device_id")
    private Long deviceId;
}
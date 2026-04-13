import {
  Card,
  Form,
  Switch,
  InputNumber,
  Select,
  Alert,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

const AUXILIARY_MODEL_OPTIONS = [
  { value: "", label: "使用主模型" },
  { value: "qwen-turbo", label: "Qwen Turbo (快速)" },
  { value: "qwen-plus", label: "Qwen Plus (平衡)" },
  { value: "haiku", label: "Claude Haiku (低成本)" },
];

interface LearningConfigCardProps {
  learningEnabled: boolean;
}

export function LearningConfigCard({ learningEnabled }: LearningConfigCardProps) {
  const { t } = useTranslation();

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.learningTitle")}
      style={{ marginTop: 16 }}
      extra={
        <Form.Item name={["learning", "enabled"]} noStyle>
          <Switch
            checkedChildren={t("common.enabled")}
            unCheckedChildren={t("common.disabled")}
          />
        </Form.Item>
      }
    >
      {learningEnabled && (
        <>
          <Alert
            type="info"
            showIcon
            message={t("agentConfig.learningInfo")}
            style={{ marginBottom: 16 }}
          />

          <Form.Item
            label={t("agentConfig.memoryNudgeInterval")}
            name={["learning", "memory_nudge_interval"]}
            rules={[
              {
                required: true,
                message: t("agentConfig.memoryNudgeIntervalRequired"),
              },
              {
                type: "number",
                min: 1,
                max: 100,
                message: t("agentConfig.memoryNudgeIntervalRange"),
              },
            ]}
            tooltip={t("agentConfig.memoryNudgeIntervalTooltip")}
          >
            <InputNumber
              style={{ width: "100%" }}
              min={1}
              max={100}
              placeholder="10"
            />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.skillNudgeInterval")}
            name={["learning", "skill_nudge_interval"]}
            rules={[
              {
                required: true,
                message: t("agentConfig.skillNudgeIntervalRequired"),
              },
              {
                type: "number",
                min: 1,
                max: 50,
                message: t("agentConfig.skillNudgeIntervalRange"),
              },
            ]}
            tooltip={t("agentConfig.skillNudgeIntervalTooltip")}
          >
            <InputNumber
              style={{ width: "100%" }}
              min={1}
              max={50}
              placeholder="5"
            />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.maxSkills")}
            name={["learning", "max_skills"]}
            rules={[
              {
                required: true,
                message: t("agentConfig.maxSkillsRequired"),
              },
              {
                type: "number",
                min: 10,
                max: 200,
                message: t("agentConfig.maxSkillsRange"),
              },
            ]}
            tooltip={t("agentConfig.maxSkillsTooltip")}
          >
            <InputNumber
              style={{ width: "100%" }}
              min={10}
              max={200}
              placeholder="50"
            />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.patternExtraction")}
            name={["learning", "enable_pattern_extraction"]}
            valuePropName="checked"
            tooltip={t("agentConfig.patternExtractionTooltip")}
          >
            <Switch />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.skillCreation")}
            name={["learning", "enable_skill_creation"]}
            valuePropName="checked"
            tooltip={t("agentConfig.skillCreationTooltip")}
          >
            <Switch />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.backgroundLearning")}
            name={["learning", "background_learning"]}
            valuePropName="checked"
            tooltip={t("agentConfig.backgroundLearningTooltip")}
          >
            <Switch />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.minPatternConfidence")}
            name={["learning", "min_pattern_confidence"]}
            rules={[
              {
                required: true,
                message: t("agentConfig.minPatternConfidenceRequired"),
              },
              {
                type: "number",
                min: 0,
                max: 1,
                message: t("agentConfig.minPatternConfidenceRange"),
              },
            ]}
            tooltip={t("agentConfig.minPatternConfidenceTooltip")}
          >
            <InputNumber
              style={{ width: "100%" }}
              min={0}
              max={1}
              step={0.1}
              placeholder="0.5"
            />
          </Form.Item>

          <Form.Item
            label={t("agentConfig.auxiliaryModel")}
            name={["learning", "auxiliary_model"]}
            tooltip={t("agentConfig.auxiliaryModelTooltip")}
          >
            <Select
              options={AUXILIARY_MODEL_OPTIONS}
              style={{ width: "100%" }}
              allowClear
              placeholder={t("agentConfig.auxiliaryModelPlaceholder")}
            />
          </Form.Item>

          <Alert
            type="warning"
            showIcon
            message={t("agentConfig.learningRestartWarning")}
            style={{ marginTop: 16 }}
          />
        </>
      )}
    </Card>
  );
}
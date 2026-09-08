package inference_test

import (
	"math"
	"testing"

	"github.com/Keshav76315/turboSH/core/inference"
)

func TestShannonEntropy(t *testing.T) {
	// Empty or single count should have 0 entropy
	if ent := inference.ShannonEntropy([]int{}); ent != 0 {
		t.Errorf("Expected 0 entropy for empty counts, got %f", ent)
	}
	if ent := inference.ShannonEntropy([]int{10}); ent != 0 {
		t.Errorf("Expected 0 entropy for single endpoint, got %f", ent)
	}

	// 2 endpoints hit equally should be normalized entropy 1.0 (log2(2) / log2(2) = 1.0)
	counts2 := []int{5, 5}
	ent2 := inference.ShannonEntropy(counts2)
	if math.Abs(float64(ent2)-1.0) > 0.0001 {
		t.Errorf("Expected entropy ~1.0 for 2 equal endpoints, got %f", ent2)
	}

	// 4 endpoints hit equally should also normalize to 1.0 (log2(4) / log2(4) = 1.0)
	counts4 := []int{5, 5, 5, 5}
	ent4 := inference.ShannonEntropy(counts4)
	if math.Abs(float64(ent4)-1.0) > 0.0001 {
		t.Errorf("Expected normalized entropy ~1.0 for 4 equal endpoints, got %f", ent4)
	}

	// Zero counts in the array should be ignored in endpoint count calculation
	countsWithZero := []int{5, 0, 5}
	entZero := inference.ShannonEntropy(countsWithZero)
	if math.Abs(float64(entZero)-1.0) > 0.0001 {
		t.Errorf("Expected normalized entropy ~1.0 for 2 non-zero equal endpoints, got %f", entZero)
	}

	// Skewed distribution should be between 0.0 and 1.0
	countsSkewed := []int{90, 10}
	entSkewed := inference.ShannonEntropy(countsSkewed)
	if entSkewed <= 0.0 || entSkewed >= 1.0 {
		t.Errorf("Expected entropy between 0.0 and 1.0 for skewed distribution, got %f", entSkewed)
	}
}

// NOTE: We cannot easily unit test the actual ONNX runtime in full CI without
// bundling the ONNX shared library (.so / .dll / .dylib). The below is a stub
// documenting how to execute the test locally once the DLL is installed.

/*
func TestPredict(t *testing.T) {
	// 1. Point to your local ORT shared library
	// err := inference.Initialize("/path/to/onnxruntime.dll")
	// defer inference.Destroy()

	// 2. Load engine
	// engine, err := inference.NewEngine("../../models/anomaly_model.onnx")
	// defer engine.Close()

	// 3. Score Normal Traffic
	// normal := inference.RequestFeatures{ ... }
	// score, err := engine.Predict(normal)
	// if score != 0.0 { t.Error("Normal traffic should be 0.0") }

	// 4. Score Attack Traffic
	// attack := inference.RequestFeatures{ ... }
	// score, err = engine.Predict(attack)
	// if score != 1.0 { t.Error("Attack traffic should be 1.0") }
}
*/

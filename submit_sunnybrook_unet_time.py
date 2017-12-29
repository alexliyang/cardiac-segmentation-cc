#!/usr/bin/env python2.7

import re, sys, os
import shutil, cv2
import numpy as np

from train_sunnybrook_unet_time import read_contour, map_all_contours, export_all_contours, map_endo_contours
from helpers import reshape, get_SAX_SERIES, draw_result
from unet_model_time import unet_model_time, dice_coef_endo_each, dice_coef_myo_each

SAX_SERIES = get_SAX_SERIES()
SUNNYBROOK_ROOT_PATH = 'D:\cardiac_data\Sunnybrook'
VAL_CONTOUR_PATH = os.path.join(SUNNYBROOK_ROOT_PATH,
                                'Sunnybrook Cardiac MR Database ContoursPart2',
                                'ValidationDataContours')
VAL_IMG_PATH = os.path.join(SUNNYBROOK_ROOT_PATH,
                            'Sunnybrook Cardiac MR Database DICOMPart2',
                            'ValidationDataDICOM')
VAL_OVERLAY_PATH = os.path.join(SUNNYBROOK_ROOT_PATH,
                                'Sunnybrook Cardiac MR Database OverlayPart2',
                                'ValidationDataOverlay')
ONLINE_CONTOUR_PATH = os.path.join(SUNNYBROOK_ROOT_PATH,
                                   'Sunnybrook Cardiac MR Database ContoursPart1',
                                   'OnlineDataContours')
ONLINE_IMG_PATH = os.path.join(SUNNYBROOK_ROOT_PATH,
                               'Sunnybrook Cardiac MR Database DICOMPart1',
                               'OnlineDataDICOM')
ONLINE_OVERLAY_PATH = os.path.join(SUNNYBROOK_ROOT_PATH,
                                   'Sunnybrook Cardiac MR Database OverlayPart1',
                                   'OnlineDataOverlay')
SAVE_VAL_PATH = os.path.join(SUNNYBROOK_ROOT_PATH,
                             'Sunnybrook_val_submission')
SAVE_ONLINE_PATH = os.path.join(SUNNYBROOK_ROOT_PATH,
                                'Sunnybrook_online_submission')


def create_submission(contours, data_path, output_path, contour_type='a'):
    if contour_type == 'a':
        weights = 'model_logs/temp_weights.hdf5'
    else:
        sys.exit('\ncontour type "%s" not recognized\n' % contour_type)
    num_phases = 9
    crop_size = 128
    input_shape = (num_phases, crop_size, crop_size, 1)
    num_classes = 3
    images, masks = export_all_contours(contours, data_path, output_path, crop_size, num_classes=num_classes, num_phases=num_phases)
    model = unet_model_time(input_shape, downsize_filters_factor=2, pool_size=(1, 2, 2), n_labels=3,
                  initial_learning_rate=0.00001, deconvolution=False, weights=weights)

    pred_masks = model.predict(images, batch_size=8, verbose=1)
    print('\nEvaluating dev set ...')
    result = model.evaluate(images, masks, batch_size=8)
    result = np.round(result, decimals=10)
    print('\nDev set result {:s}:\n{:s}'.format(str(model.metrics_names), str(result)))
    num = 0

    for c_type in ['i', 'm']:
        for idx, ctr in enumerate(contours):
            img, mask = read_contour(ctr, data_path, num_classes, num_phases=1, num_phases_in_cycle=20, phase_dilation=1)
            p, h, w, d = img.shape
            if c_type == 'i':
                tmp = pred_masks[idx, 0, ..., 2]
            elif c_type == 'm':
                tmp = pred_masks[idx, 0, ..., 1]

            tmp = tmp[..., np.newaxis]
            tmp = reshape(tmp, to_shape=(h, w, d))
            tmp = np.where(tmp > 0.5, 255, 0).astype('uint8')
            tmp2, coords, hierarchy = cv2.findContours(tmp.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
            if not coords:
                print('\nNo detection in case: {:s}; image: {:d}'.format(ctr.case, ctr.img_no))
                coords = np.ones((1, 1, 1, 2), dtype='int')

            if c_type == 'i':
                man_filename = ctr.ctr_endo_path[ctr.ctr_endo_path.rfind('\\') + 1:]
            elif c_type == 'm':
                man_filename = ctr.ctr_epi_path[ctr.ctr_epi_path.rfind('\\') + 1:]

            auto_filename = man_filename.replace('manual', 'auto')
            img_filename = re.sub(r'-[io]contour-manual.txt', '.dcm', man_filename)
            man_full_path = os.path.join(save_dir, ctr.case, 'contours-manual', 'IRCCI-expert')
            auto_full_path = os.path.join(save_dir, ctr.case, 'contours-auto', 'FCN')
            img_full_path = os.path.join(save_dir, ctr.case, 'DICOM')
            dcm = 'IM-0001-%04d.dcm' % (ctr.img_no)
            # dcm = 'IM-%s-%04d.dcm' % (SAX_SERIES[ctr.case], ctr.img_no)
            dcm_path = os.path.join(data_path, ctr.case, 'DICOM', dcm)
            overlay_full_path = os.path.join(save_dir, ctr.case, 'Overlay')
            for dirpath in [man_full_path, auto_full_path, img_full_path, overlay_full_path]:
                if not os.path.exists(dirpath):
                    os.makedirs(dirpath)
                if 'DICOM' in dirpath:
                    src = dcm_path
                    dst = os.path.join(dirpath, img_filename)
                    shutil.copyfile(src, dst)
                elif 'Overlay' in dirpath:
                    draw_result(ctr, data_path, overlay_full_path, c_type, coords)
                else:
                    dst = os.path.join(auto_full_path, auto_filename)
                    if not os.path.exists(auto_full_path):
                        os.makedirs(auto_full_path)
                    with open(dst, 'wb') as f:
                        for cd in coords:
                            cd = np.squeeze(cd)
                            if cd.ndim == 1:
                                np.savetxt(f, cd, fmt='%d', delimiter=' ')
                            else:
                                for coord in cd:
                                    np.savetxt(f, coord, fmt='%d', delimiter=' ')

        print('\nNumber of multiple detections: {:d}'.format(num))
        dst_eval = os.path.join(save_dir, 'evaluation_{:s}.txt'.format(c_type))
        with open(dst_eval, 'wb') as f:
            f.write(('Dev set result {:s}:\n{:s}'.format(str(model.metrics_names), str(result))).encode('utf-8'))
            f.close()

        # Detailed evaluation:
        detail_eval = os.path.join(save_dir, 'evaluation_detail_{:s}.csv'.format(c_type))
        evalEndoArr = dice_coef_endo_each(masks, pred_masks)
        evalMyoArr = dice_coef_myo_each(masks, pred_masks)
        caseArr = [ctr.case for ctr in contours]
        imgArr = [ctr.img_no for ctr in contours]
        resArr = np.transpose([caseArr, imgArr, evalEndoArr, evalMyoArr])
        np.savetxt(detail_eval, resArr, fmt='%s', delimiter=',')


        # np.savetxt(f, '\nDev set result {:s}:\n{:s}'.format(str(model.metrics_names), str(result)))


def create_endo_submission(endos, data_path, output_path, contour_type='a'):
    if contour_type == 'a':
        weights = 'model_logs/temp_weights.hdf5'
    else:
        sys.exit('\ncontour type "%s" not recognized\n' % contour_type)

    num_phases = 9
    crop_size = 128
    input_shape = (num_phases, crop_size, crop_size, 1)
    num_classes = 3
    images, masks = export_all_contours(endos, data_path, output_path, crop_size, num_classes=num_classes, num_phases=num_phases)
    model = unet_model_time(input_shape, downsize_filters_factor=2, pool_size=(1, 2, 2), n_labels=3,
                  initial_learning_rate=0.00001, deconvolution=False, weights=weights)

    pred_masks = model.predict(images, batch_size=8, verbose=1)
    print('\nEvaluating dev set ...')
    result = model.evaluate(images, masks, batch_size=8)
    result = np.round(result, decimals=10)
    print('\nDev set result {:s}:\n{:s}'.format(str(model.metrics_names), str(result)))
    num = 0

    c_type = 'i'
    for idx, ctr in enumerate(endos):
        img, mask = read_contour(ctr, data_path, num_classes, num_phases=1, num_phases_in_cycle=20, phase_dilation=1)
        h, w, d = img.shape
        if c_type == 'i':
            tmp = pred_masks[idx, 0, ..., 2]
        elif c_type == 'm':
            tmp = pred_masks[idx, 0, ..., 1]

        tmp = tmp[..., np.newaxis]
        tmp = reshape(tmp, to_shape=(h, w, d))
        tmp = np.where(tmp > 0.5, 255, 0).astype('uint8')
        tmp2, coords, hierarchy = cv2.findContours(tmp.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        if not coords:
            print('\nNo detection in case: {:s}; image: {:d}'.format(ctr.case, ctr.img_no))
            coords = np.ones((1, 1, 1, 2), dtype='int')

        if c_type == 'i':
            man_filename = ctr.ctr_endo_path[ctr.ctr_endo_path.rfind('\\') + 1:]
        elif c_type == 'm':
            man_filename = ctr.ctr_epi_path[ctr.ctr_epi_path.rfind('\\') + 1:]

        auto_filename = man_filename.replace('manual', 'auto')
        img_filename = re.sub(r'-[io]contour-manual.txt', '.dcm', man_filename)
        man_full_path = os.path.join(save_dir, ctr.case, 'contours-manual', 'IRCCI-expert')
        auto_full_path = os.path.join(save_dir, ctr.case, 'contours-auto', 'FCN')
        img_full_path = os.path.join(save_dir, ctr.case, 'DICOM')
        dcm = 'IM-0001-%04d.dcm' % (ctr.img_no)
        # dcm = 'IM-%s-%04d.dcm' % (SAX_SERIES[ctr.case], ctr.img_no)
        dcm_path = os.path.join(data_path, ctr.case, 'DICOM', dcm)
        overlay_full_path = os.path.join(save_dir, ctr.case, 'Overlay')
        for dirpath in [man_full_path, auto_full_path, img_full_path, overlay_full_path]:
            if not os.path.exists(dirpath):
                os.makedirs(dirpath)
            if 'DICOM' in dirpath:
                src = dcm_path
                dst = os.path.join(dirpath, img_filename)
                shutil.copyfile(src, dst)
            elif 'Overlay' in dirpath:
                draw_result(ctr, data_path, overlay_full_path, c_type, coords)
            else:
                dst = os.path.join(auto_full_path, auto_filename)
                if not os.path.exists(auto_full_path):
                    os.makedirs(auto_full_path)
                with open(dst, 'wb') as f:
                    for cd in coords:
                        cd = np.squeeze(cd)
                        if cd.ndim == 1:
                            np.savetxt(f, cd, fmt='%d', delimiter=' ')
                        else:
                            for coord in cd:
                                np.savetxt(f, coord, fmt='%d', delimiter=' ')

    print('\nNumber of multiple detections: {:d}'.format(num))
    dst_eval = os.path.join(save_dir, 'evaluation_{:s}.txt'.format(c_type))
    with open(dst_eval, 'wb') as f:
        f.write(('Dev set result {:s}:\n{:s}'.format(str(model.metrics_names), str(result))).encode('utf-8'))
        f.close()

    # Detailed evaluation:
    detail_eval = os.path.join(save_dir, 'evaluation_detail_{:s}.csv'.format(c_type))
    evalEndoArr = dice_coef_endo_each(masks, pred_masks)
    evalMyoArr = dice_coef_myo_each(masks, pred_masks)
    caseArr = [ctr.case for ctr in endos]
    imgArr = [ctr.img_no for ctr in endos]
    resArr = np.transpose([caseArr, imgArr, evalEndoArr, evalMyoArr])
    np.savetxt(detail_eval, resArr, fmt='%s', delimiter=',')


if __name__ == '__main__':
    contour_type = 'a'
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'

    save_dir = 'D:\cardiac_data\Sunnybrook\Sunnybrook_online_submission_unet_time'
    print('\nProcessing online ' + contour_type + ' contours...')
    online_ctrs = list(map_all_contours(ONLINE_CONTOUR_PATH))
    online_endos = list(map_endo_contours(ONLINE_CONTOUR_PATH))
    create_submission(online_ctrs, ONLINE_IMG_PATH, ONLINE_OVERLAY_PATH, contour_type)
    create_endo_submission(online_endos, ONLINE_IMG_PATH, ONLINE_OVERLAY_PATH, contour_type)

    save_dir = 'D:\cardiac_data\Sunnybrook\Sunnybrook_val_submission_unet_time'
    print('\nProcessing val ' + contour_type + ' contours...')
    val_ctrs = list(map_all_contours(VAL_CONTOUR_PATH))
    val_endos = list(map_endo_contours(VAL_CONTOUR_PATH))
    create_submission(val_ctrs, VAL_IMG_PATH, VAL_OVERLAY_PATH, contour_type)
    create_endo_submission(val_endos, VAL_IMG_PATH, VAL_OVERLAY_PATH, contour_type)

    print('\nAll done.')
